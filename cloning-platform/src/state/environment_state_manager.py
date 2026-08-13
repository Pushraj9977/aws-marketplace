"""
environment_state_manager.py — CRUD operations for the EnvironmentState DynamoDB table.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from ..common.constants import EnvironmentStatus, ResourceStatus
from ..common.exceptions import StateManagerError
from ..common.logger import get_logger
from ..common.models import EnvironmentModel, ResourceRecord

logger = get_logger(__name__)


class EnvironmentStateManager:
    """
    Repository for all EnvironmentState DynamoDB operations.

    Table schema:
        PK: environment_id (S)
        GSI: status-index on status (S)
    """

    def __init__(self, table_name: str, region: str = "eu-central-1") -> None:
        self.table_name = table_name
        self._ddb = boto3.resource("dynamodb", region_name=region)
        self._table = self._ddb.Table(table_name)

    def create(self, env: EnvironmentModel) -> None:
        """
        Write a new EnvironmentModel to DynamoDB.

        Args:
            env: The environment model to persist.

        Raises:
            StateManagerError: On DynamoDB write failure.
        """
        try:
            item = env.model_dump(mode="json")
            item["started_at"] = env.started_at.isoformat()
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(environment_id)",
            )
            logger.info("EnvironmentState created", extra={"environment_id": env.environment_id})
        except self._ddb.meta.client.exceptions.ConditionalCheckFailedException:
            raise StateManagerError(
                f"Environment already exists: {env.environment_id}",
                resource_id=env.environment_id,
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to create environment state: {exc}") from exc

    def get(self, environment_id: str) -> EnvironmentModel:
        """
        Fetch an EnvironmentModel by its ID.

        Args:
            environment_id: The UUID of the environment.

        Returns:
            EnvironmentModel instance.

        Raises:
            StateManagerError: If not found or read fails.
        """
        try:
            resp = self._table.get_item(Key={"environment_id": environment_id})
            item = resp.get("Item")
            if not item:
                raise StateManagerError(
                    f"Environment not found: {environment_id}",
                    resource_id=environment_id,
                )
            return EnvironmentModel.model_validate(item)
        except StateManagerError:
            raise
        except Exception as exc:
            raise StateManagerError(f"Failed to get environment state: {exc}") from exc

    def update_status(self, environment_id: str, status: EnvironmentStatus) -> None:
        """
        Update the top-level status of an environment.

        Args:
            environment_id: The UUID of the environment.
            status: The new EnvironmentStatus value.
        """
        try:
            update_expr = "SET #s = :s, updated_at = :u"
            if status == EnvironmentStatus.ACTIVE:
                update_expr += ", completed_at = :c"
                extra: dict[str, Any] = {":c": datetime.now(timezone.utc).isoformat()}
            else:
                extra = {}
            self._table.update_item(
                Key={"environment_id": environment_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": status.value,
                    ":u": datetime.now(timezone.utc).isoformat(),
                    **extra,
                },
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to update status: {exc}") from exc

    def upsert_resource(self, environment_id: str, record: ResourceRecord) -> None:
        """
        Insert or update a ResourceRecord within the environment's resources map.

        Args:
            environment_id: The UUID of the environment.
            record: The ResourceRecord to upsert.
        """
        key = f"{record.resource_type}:{record.source_id}"
        try:
            self._table.update_item(
                Key={"environment_id": environment_id},
                UpdateExpression="SET resources.#k = :r, updated_at = :u",
                ExpressionAttributeNames={"#k": key},
                ExpressionAttributeValues={
                    ":r": record.model_dump(mode="json"),
                    ":u": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to upsert resource record: {exc}") from exc

    def update_field(self, environment_id: str, field: str, value: Any) -> None:
        """Update a top-level scalar field on the environment record."""
        try:
            self._table.update_item(
                Key={"environment_id": environment_id},
                UpdateExpression="SET #f = :v, updated_at = :u",
                ExpressionAttributeNames={"#f": field},
                ExpressionAttributeValues={
                    ":v": value,
                    ":u": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to update field {field}: {exc}") from exc

    def sync_environment(self, env: EnvironmentModel) -> None:
        """Persist the top-level mutable environment fields updated during provisioning."""
        excluded = {
            "resources",
            "started_at",
            "completed_at",
            "admin_password",
        }
        payload = env.model_dump(mode="json", exclude=excluded)
        payload.pop("environment_id", None)
        payload.pop("status", None)
        for field, value in payload.items():
            self.update_field(env.environment_id, field, value)
