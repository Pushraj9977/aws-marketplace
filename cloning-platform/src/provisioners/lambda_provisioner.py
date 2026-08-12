"""
lambda_provisioner.py — Clone Lambda functions from source to target environment.
Downloads source code package and deploys new functions with updated env vars.
"""
from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path

from ..common.constants import ResourceType
from ..common.exceptions import SourceResourceNotFoundError
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import build_lambda_arn, merge_env_vars, retry
from .base import BaseProvisioner


class LambdaProvisioner(BaseProvisioner):
    """Clones all Lambda functions matching source_env_name to target_env_name."""

    resource_type = ResourceType.LAMBDA_FUNCTION

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        lam = self.get_client("lambda")

        # Discover source functions
        source_functions = self._list_source_functions(lam, env.source_env_name)
        if not source_functions:
            raise SourceResourceNotFoundError(
                f"No Lambda functions found matching source env: {env.source_env_name}",
                resource_type=str(self.resource_type),
            )

        created: list[str] = []
        skipped: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            for source_name in source_functions:
                target_name = source_name.replace(env.source_env_name, env.target_env_name)

                # Idempotency
                if self._function_exists(lam, target_name):
                    self.logger.warning("Lambda already exists, skipping", extra={"fn": target_name})
                    skipped.append(target_name)
                    continue

                self.logger.info("Cloning Lambda", extra={"source": source_name, "target": target_name})

                # Download source package
                zip_path = Path(tmpdir) / f"{target_name}.zip"
                source_cfg = self._download_package(lam, source_name, zip_path)

                # Create new function
                self._create_function(lam, source_cfg, target_name, zip_path, env)
                created.append(target_name)

        # Update env vars on ALL cloned functions after Cognito + API GW are known
        all_targets = created + skipped
        for target_name in all_targets:
            self._inject_env_vars(lam, target_name, env)

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=",".join(all_targets),
            target_arn=build_lambda_arn(self.region, self.account_id, all_targets[0]) if all_targets else "",
            metadata={"created": created, "skipped": skipped},
        )

    def _list_source_functions(self, lam: object, source_env: str) -> list[str]:
        names: list[str] = []
        paginator = lam.get_paginator("list_functions")  # type: ignore[attr-defined]
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                if source_env in fn["FunctionName"]:
                    names.append(fn["FunctionName"])
        return names

    def _function_exists(self, lam: object, name: str) -> bool:
        try:
            lam.get_function(FunctionName=name)  # type: ignore[attr-defined]
            return True
        except lam.exceptions.ResourceNotFoundException:  # type: ignore[attr-defined]
            return False

    def _download_package(self, lam: object, source_name: str, zip_path: Path) -> dict:
        resp = lam.get_function(FunctionName=source_name)  # type: ignore[attr-defined]
        code_url = resp["Code"]["Location"]
        urllib.request.urlretrieve(code_url, zip_path)
        self.logger.info(
            "Package downloaded",
            extra={"source": source_name, "size_kb": zip_path.stat().st_size // 1024},
        )
        return resp["Configuration"]

    @retry(max_attempts=3, delay_seconds=5.0)
    def _create_function(
        self,
        lam: object,
        source_cfg: dict,
        target_name: str,
        zip_path: Path,
        env: EnvironmentModel,
    ) -> None:
        kwargs: dict = {
            "FunctionName": target_name,
            "Runtime": source_cfg["Runtime"],
            "Handler": source_cfg["Handler"],
            "Role": env.iam_role_arn or source_cfg["Role"],
            "Code": {"ZipFile": zip_path.read_bytes()},
            "Timeout": source_cfg["Timeout"],
            "MemorySize": source_cfg["MemorySize"],
            "Description": f"Cloned for environment: {env.target_env_name}",
        }
        if source_cfg.get("Architectures"):
            kwargs["Architectures"] = source_cfg["Architectures"]
        if source_cfg.get("Layers"):
            kwargs["Layers"] = [layer["Arn"] for layer in source_cfg["Layers"]]

        lam.create_function(**kwargs)  # type: ignore[attr-defined]

        # Wait for function to become active
        waiter = lam.get_waiter("function_active_v2")  # type: ignore[attr-defined]
        waiter.wait(FunctionName=target_name)
        self.logger.info("Lambda active", extra={"function": target_name})

    def _inject_env_vars(self, lam: object, target_name: str, env: EnvironmentModel) -> None:
        """Merge source env vars with new environment-specific overrides."""
        try:
            resp = lam.get_function_configuration(FunctionName=target_name)  # type: ignore[attr-defined]
            base_vars = resp.get("Environment", {}).get("Variables", {})
        except Exception:
            base_vars = {}

        # Build the DynamoDB table names for this tenant environment.
        # Convention: source table names have the source env name replaced with target.
        # For the initial release, tables are shared (same name) but injected via env var
        # so future per-tenant tables can be created by the DynamoDB provisioner and
        # inserted into env.dynamodb_table_names without changing this code.
        overrides = {
            "ENV": env.target_env_name,
            "ENV_NAME": env.target_env_name,
            "REGION": self.region,
            "USER_POOL_ID": env.user_pool_id,
            "APP_CLIENT_ID": env.app_client_id,
            # Secret name — runtime secret lookup
            "SECRET_NAME": env.secret_name,
            "SECRET_MANAGER_KEY": "HealthyLivingProd/catalyst/KeyJune2025",
            "SECRET_ACCESS_KEY_REGION": self.region,
            # Cognito / Frontend identifiers
            "NEXT_PUBLIC_USER_POOL_ID": env.user_pool_id,
            "NEXT_PUBLIC_CDN_URL": "https://d3kpamwwj9ilmr.cloudfront.net",
            "NEXT_PUBLIC_S3Bucket": "healthy-aging-buckets-frankfurt-538594436951-eu-central-1-an",
            # DynamoDB table names — keyed exactly as the Lambda source code reads them
            "CatEncounter_Users_Table": f"CatEncounter_Users_Table-{env.target_env_name}",
            "CatEncounter_Membership_Table": f"catEncounter_Membership_Table-{env.target_env_name}",
            "CatEncounter_StaffTable": f"catEncounter_StaffTable-{env.target_env_name}",
            "Thought_Table": f"Thought_Table-{env.target_env_name}",
            "Picture_Table": f"Picture_Table-{env.target_env_name}",
            "CatEncounter_Event_Table": f"catEncounter_Event_Table-{env.target_env_name}",
            "Event_Landing_Notes": f"Event_Landing_Notes-{env.target_env_name}",
            "Member_Landing_Notes": f"Member_Landing_Notes-{env.target_env_name}",
            "Staff_Landing_Notes": f"Staff_Landing_Notes-{env.target_env_name}",
            "CatEncounter_Dashboard_MessageBoard": f"catEncounter_Dashboard_MessageBoard-{env.target_env_name}",
            "CheckIn_Table": f"CheckIn_Table-{env.target_env_name}",
            "StaffCheckIn_Table": f"StaffCheckIn_Table-{env.target_env_name}",
            "CatEncounter_RecommendedEvent": f"CatEncounter_RecommendedEvent-{env.target_env_name}",
            "catEncourageStaffAssignments": f"catEncourageStaffAssignments-{env.target_env_name}",
            "Catalyst_CompConfig": f"Catalyst_CompConfig-{env.target_env_name}",
            "memberAssessments": f"memberAssessments-{env.target_env_name}",
            "memberPlans": f"memberPlans-{env.target_env_name}",
            "FeelingMeter": f"FeelingMeter-{env.target_env_name}",
            # Heart Rhythm tables (not tenant-specific — shared)
            "HeartRhythm_User_Table": "HeartRhythm_User_Table",
            "HeartRhythm_Prescriptions_Table": "HeartRhythm_Prescriptions_Table",
            "HeartRhythm_Results_Table": "HeartRhythm_Results_Table",
            "Heart_Rhythm_Transaction_Log": "Heart_Rhythm_Transaction_Log",
            "HeartRhythm_Prescriptions_History_Table": "HeartRhythm_Prescriptions_History_Table",
        }
        merged = merge_env_vars(base_vars, overrides)

        lam.update_function_configuration(  # type: ignore[attr-defined]
            FunctionName=target_name,
            Environment={"Variables": merged},
        )
        waiter = lam.get_waiter("function_updated_v2")  # type: ignore[attr-defined]
        waiter.wait(FunctionName=target_name)

    def validate(self, record: ResourceRecord) -> bool:
        lam = self.get_client("lambda")
        first_fn = (record.target_id or "").split(",")[0]
        if not first_fn:
            return True
        try:
            resp = lam.get_function_configuration(FunctionName=first_fn)
            return resp.get("State") == "Active"
        except Exception:
            return False
