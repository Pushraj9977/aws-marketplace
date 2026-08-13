"""
health_check.py — Lambda handler to validate all cloned resources are alive.
"""
from __future__ import annotations

import urllib.request
import urllib.error
from typing import Any

import boto3

from ..common.config import get_config
from ..common.logger import get_logger
from ..common.models import EnvironmentModel, HealthCheckResult
from ..state.environment_state_manager import EnvironmentStateManager

logger = get_logger(__name__)
config = get_config()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda entry point for health checks.

    Args:
        event: Contains environment_id and environment snapshot.
        context: Lambda context.

    Returns:
        { "passed": bool, "checks": { resource: bool }, "errors": [] }
    """
    env_data = event.get("environment", {})
    environment_id = env_data.get("environment_id", "")
    logger.info("HealthCheck invoked", extra={"environment_id": environment_id})

    state_mgr = EnvironmentStateManager(
        table_name=config.environment_state_table,
        region=config.region,
    )
    env = state_mgr.get(environment_id)
    service = HealthCheckService(region=config.region)
    result = service.check_all(env)

    logger.info(
        "HealthCheck result",
        extra={
            "environment_id": environment_id,
            "passed": result.passed,
            "checks": result.checks,
        },
    )

    if not result.passed:
        # Step Functions will catch this as a failure
        raise RuntimeError(
            f"Health check failed for {environment_id}: {result.errors}"
        )

    return {
        "environment": env_data,
        "health_check": result.model_dump(mode="json")
    }


class HealthCheckService:
    """Validates all cloned AWS resources are operational."""

    def __init__(self, region: str) -> None:
        self.region = region

    def check_all(self, env: EnvironmentModel) -> HealthCheckResult:
        """Run all health checks for the given environment."""
        checks: dict[str, bool] = {}
        errors: list[str] = []

        # 1. DynamoDB tables
        for table_name in self._get_table_names(env):
            ok = self._validate_dynamodb(table_name)
            checks[f"dynamodb:{table_name}"] = ok
            if not ok:
                errors.append(f"DynamoDB table not ACTIVE: {table_name}")

        # 2. Cognito User Pool
        if env.user_pool_id:
            ok = self._validate_cognito(env.user_pool_id)
            checks[f"cognito:{env.user_pool_id}"] = ok
            if not ok:
                errors.append(f"Cognito pool not enabled: {env.user_pool_id}")

        # 3. Lambda Functions
        for fn_name in self._get_lambda_names(env):
            ok = self._validate_lambda(fn_name)
            checks[f"lambda:{fn_name}"] = ok
            if not ok:
                errors.append(f"Lambda not active: {fn_name}")

        # 4. API Endpoints
        for fn_name, api_url in env.api_urls.items():
            ok = self._probe_api(api_url)
            checks[f"api:{fn_name}"] = ok
            if not ok:
                errors.append(f"API not reachable: {api_url}")

        return HealthCheckResult(
            passed=len(errors) == 0,
            checks=checks,
            errors=errors,
        )

    def _get_table_names(self, env: EnvironmentModel) -> list[str]:
        from ..common.constants import ResourceType
        for key, record in env.resources.items():
            if ResourceType.DYNAMODB_TABLE in key:
                if record.metadata.get("skipped") or record.target_id == "shared-database":
                    return []
                return record.target_id.split(",") if record.target_id else []
        return []

    def _get_lambda_names(self, env: EnvironmentModel) -> list[str]:
        from ..common.constants import ResourceType
        for key, record in env.resources.items():
            if ResourceType.LAMBDA_FUNCTION in key:
                return record.target_id.split(",") if record.target_id else []
        return []

    def _validate_dynamodb(self, table_name: str) -> bool:
        try:
            ddb = boto3.client("dynamodb", region_name=self.region)
            resp = ddb.describe_table(TableName=table_name)
            return resp["Table"]["TableStatus"] == "ACTIVE"
        except Exception:
            return False

    def _validate_cognito(self, pool_id: str) -> bool:
        try:
            idp = boto3.client("cognito-idp", region_name=self.region)
            resp = idp.describe_user_pool(UserPoolId=pool_id)
            return "Id" in resp.get("UserPool", {})
        except Exception:
            return False

    def _validate_lambda(self, fn_name: str) -> bool:
        try:
            lam = boto3.client("lambda", region_name=self.region)
            resp = lam.get_function_configuration(FunctionName=fn_name)
            return resp.get("State") == "Active"
        except Exception:
            return False

    def _probe_api(self, url: str) -> bool:
        """Send a HEAD request to verify the API endpoint is reachable."""
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as e:
            # 4xx errors mean the endpoint is alive (just needs auth/data)
            return e.code < 500
        except Exception:
            return False
