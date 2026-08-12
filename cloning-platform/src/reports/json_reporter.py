"""
json_reporter.py — Generates a structured JSON report from an EnvironmentModel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..common.models import EnvironmentModel


class JSONReporter:
    """Produces a machine-readable JSON report of the cloning operation."""

    def generate(self, env: EnvironmentModel) -> dict[str, Any]:
        """
        Build the full JSON report dict from an EnvironmentModel.

        Args:
            env: The completed EnvironmentModel.

        Returns:
            Structured report as a Python dict (JSON-serializable).
        """
        resources = []
        for key, record in env.resources.items():
            resources.append({
                "resource_type": record.resource_type,
                "source_id": record.source_id,
                "target_id": record.target_id,
                "target_arn": record.target_arn,
                "status": record.status,
                "error_message": record.error_message,
            })

        return {
            "report_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "environment_id": env.environment_id,
                "source_env_name": env.source_env_name,
                "target_env_name": env.target_env_name,
                "region": env.region,
                "account_id": env.account_id,
                "status": env.status,
                "started_at": env.started_at.isoformat() if env.started_at else None,
                "completed_at": env.completed_at.isoformat() if env.completed_at else None,
            },
            "subscriber": {
                "company_name": env.company_name,
                "contact_email": env.contact_email,
                "reg_token": env.reg_token,
            },
            "resources": resources,
            "endpoints": {
                "cognito_user_pool_id": env.user_pool_id,
                "cognito_app_client_id": env.app_client_id,
                "secret_name": env.secret_name,
                "api_urls": env.api_urls,
                "amplify_app_id": env.amplify_app_id,
            },
            "credentials": {
                "admin_email": getattr(env, "admin_email", ""),
                "admin_password": getattr(env, "admin_password", ""),
            },
            "summary": {
                "total_resources": len(resources),
                "done": sum(1 for r in resources if r["status"] == "DONE"),
                "failed": sum(1 for r in resources if r["status"] == "FAILED"),
                "skipped": sum(1 for r in resources if r["status"] == "SKIPPED"),
            },
        }
