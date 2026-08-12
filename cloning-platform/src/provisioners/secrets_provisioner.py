"""
secrets_provisioner.py — Clone a Secrets Manager secret from source to target env.
"""
from __future__ import annotations

from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import retry
from .base import BaseProvisioner


class SecretsProvisioner(BaseProvisioner):
    """Clones the app secret from source_env/app-secret to target_env/app-secret."""

    resource_type = ResourceType.SECRET

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        sm = self.get_client("secretsmanager")
        source_secret_name = f"{env.source_env_name}/app-secret"
        target_secret_name = env.secret_name  # already set to target/app-secret

        # Idempotency check
        try:
            existing = sm.describe_secret(SecretId=target_secret_name)
            self.logger.warning(
                "Secret already exists, reusing",
                extra={"secret": target_secret_name},
            )
            return ResourceRecord(
                resource_type=self.resource_type,
                source_id=source_secret_name,
                target_id=target_secret_name,
                target_arn=existing.get("ARN", ""),
            )
        except sm.exceptions.ResourceNotFoundException:
            pass

        # Fetch source secret value
        secret_value = self._get_source_value(sm, source_secret_name)

        # Create target secret
        resp = self._create_secret(sm, target_secret_name, secret_value, env)

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=source_secret_name,
            target_id=target_secret_name,
            target_arn=resp.get("ARN", ""),
        )

    def _get_source_value(self, sm: object, secret_name: str) -> str:
        """Fetch the source secret string, or generate a new one if not found."""
        try:
            resp = sm.get_secret_value(SecretId=secret_name)  # type: ignore[attr-defined]
            return resp.get("SecretString", "")
        except Exception:
            import secrets as _secrets
            self.logger.warning(
                "Source secret not found — generating new random secret",
                extra={"source": secret_name},
            )
            return _secrets.token_urlsafe(32)

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_secret(
        self, sm: object, name: str, value: str, env: EnvironmentModel
    ) -> dict:
        return sm.create_secret(  # type: ignore[attr-defined]
            Name=name,
            Description=f"App secret for environment: {env.target_env_name}",
            SecretString=value,
            Tags=[
                {"Key": "Environment", "Value": env.target_env_name},
                {"Key": "ManagedBy", "Value": "CloningPlatform"},
            ],
        )

    @retry(max_attempts=5, delay_seconds=2.0)
    def validate(self, record: ResourceRecord) -> bool:
        sm = self.get_client("secretsmanager")
        sm.describe_secret(SecretId=record.target_id)
        return True
