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
        ddb = self.get_client("dynamodb")

        # Discover tables that match the source environment name
        all_tables: list[str] = []
        paginator = ddb.get_paginator("list_tables")
        for page in paginator.paginate():
            all_tables.extend(page.get("TableNames", []))

        source_tables = [t for t in all_tables if env.source_env_name in t]
        if not source_tables:
            raise SourceResourceNotFoundError(
                f"No DynamoDB tables found matching source env: {env.source_env_name}",
                resource_type=str(self.resource_type),
            )

        created: list[str] = []
        skipped: list[str] = []

        for source_name in source_tables:
            target_name = source_name.replace(env.source_env_name, env.target_env_name)
            self.logger.info("Cloning table", extra={"source": source_name, "target": target_name})

            # Idempotency check
            try:
                ddb.describe_table(TableName=target_name)
                self.logger.warning("Table already exists, skipping", extra={"table": target_name})
                skipped.append(target_name)
                continue
            except ddb.exceptions.ResourceNotFoundException:
                pass

            schema = ddb.describe_table(TableName=source_name)["Table"]
            self._create_table(ddb, schema, target_name)
            created.append(target_name)

        # Wait for all newly created tables to become ACTIVE
        for table_name in created:
            self._wait_active(ddb, table_name)

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=",".join(created + skipped),
            target_arn="",
            metadata={"created": created, "skipped": skipped},
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
        ddb = self.get_client("dynamodb")
        first_table = (record.target_id or "").split(",")[0]
        if not first_table:
            return True
        try:
            resp = ddb.describe_table(TableName=first_table)
            return resp["Table"]["TableStatus"] == "ACTIVE"
        except Exception:
            return False
