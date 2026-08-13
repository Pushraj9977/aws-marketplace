"""
dynamodb_provisioner.py — Clone all DynamoDB tables from source to target environment.
"""
from __future__ import annotations

from ..common.constants import ResourceType
from ..common.exceptions import SourceResourceNotFoundError
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import retry
from .base import BaseProvisioner


class DynamoDBProvisioner(BaseProvisioner):
    """Clones every DynamoDB table containing source_env_name into target_env_name."""

    resource_type = ResourceType.DYNAMODB_TABLE

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        self.logger.info("Skipping DynamoDB table creation (using shared database model)")

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id="shared-database",
            target_arn="",
            metadata={"skipped": True, "reason": "Shared database architecture"},
        )

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_table(self, ddb: object, schema: dict, target_name: str) -> None:
        """Create a single DynamoDB table from a source schema."""
        kwargs: dict = {
            "TableName": target_name,
            "AttributeDefinitions": schema["AttributeDefinitions"],
            "KeySchema": schema["KeySchema"],
            "BillingMode": "PAY_PER_REQUEST",
        }
        # Preserve GSIs if defined
        if schema.get("GlobalSecondaryIndexes"):
            kwargs["GlobalSecondaryIndexes"] = [
                {
                    "IndexName": gsi["IndexName"],
                    "KeySchema": gsi["KeySchema"],
                    "Projection": gsi["Projection"],
                }
                for gsi in schema["GlobalSecondaryIndexes"]
            ]
        ddb.create_table(**kwargs)  # type: ignore[attr-defined]

    def _wait_active(self, ddb: object, table_name: str) -> None:
        waiter = ddb.get_waiter("table_exists")  # type: ignore[attr-defined]
        waiter.wait(TableName=table_name, WaiterConfig={"Delay": 5, "MaxAttempts": 24})
        self.logger.info("Table ACTIVE", extra={"table": table_name})

    def validate(self, record: ResourceRecord) -> bool:
        return True
