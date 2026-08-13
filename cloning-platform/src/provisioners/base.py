"""
base.py — Abstract BaseProvisioner using Template Method pattern.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import boto3

from ..common.constants import ResourceStatus, ResourceType
from ..common.exceptions import ProvisioningError
from ..common.logger import get_logger
from ..common.models import EnvironmentModel, ResourceRecord
from ..state.environment_state_manager import EnvironmentStateManager


class BaseProvisioner(ABC):
    """
    Abstract base class for all AWS resource provisioners.

    Subclasses implement:
        - resource_type  (class attribute)
        - _already_exists(name) -> bool
        - _create(env) -> ResourceRecord
        - validate(record) -> bool

    The public provision() method is the Template Method:
        1. Check if resource already exists (idempotency)
        2. Mark IN_PROGRESS in state
        3. Call _create()
        4. Mark DONE in state
        5. Validate the result
    """

    resource_type: ResourceType  # Must be set by each subclass

    def __init__(
        self,
        region: str,
        account_id: str,
        state_manager: EnvironmentStateManager,
    ) -> None:
        self.region = region
        self.account_id = account_id
        self.state_manager = state_manager
        self.logger = get_logger(
            self.__class__.__module__,
            resource_type=self.resource_type,
        )

    def get_client(self, service: str) -> Any:
        """Return a boto3 client for the given AWS service."""
        return boto3.client(service, region_name=self.region)

    def provision(self, env: EnvironmentModel) -> ResourceRecord:
        """
        Template Method — orchestrates the full provisioning flow.

        Args:
            env: Current EnvironmentModel with all context.

        Returns:
            Completed ResourceRecord.

        Raises:
            ProvisioningError: If the create or validate step fails.
        """
        self.logger.info(
            "Starting provisioner",
            extra={"environment_id": env.environment_id, "step": self.resource_type},
        )

        record = ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            status=ResourceStatus.IN_PROGRESS,
        )
        self.state_manager.upsert_resource(env.environment_id, record)

        try:
            record = self._create(env)
            self.state_manager.sync_environment(env)
            record.status = ResourceStatus.DONE
            self.state_manager.upsert_resource(env.environment_id, record)
            self.logger.info(
                "Provisioner completed",
                extra={
                    "environment_id": env.environment_id,
                    "target_id": record.target_id,
                    "target_arn": record.target_arn,
                },
            )
        except Exception as exc:
            record.status = ResourceStatus.FAILED
            record.error_message = str(exc)
            self.state_manager.upsert_resource(env.environment_id, record)
            raise ProvisioningError(
                str(exc),
                resource_type=str(self.resource_type),
                resource_id=record.source_id,
            ) from exc

        try:
            is_valid = self.validate(record)
        except Exception as e:
            self.logger.error("Validation threw an exception", extra={"error": str(e), "type": str(type(e))})
            is_valid = False
            
        if not is_valid:
            record.status = ResourceStatus.FAILED
            record.error_message = "Post-create validation failed"
            self.state_manager.upsert_resource(env.environment_id, record)
            raise ProvisioningError(
                f"Validation failed for {self.resource_type}",
                resource_type=str(self.resource_type),
            )

        return record

    @abstractmethod
    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        """Create the AWS resource and return a completed ResourceRecord."""
        ...

    @abstractmethod
    def validate(self, record: ResourceRecord) -> bool:
        """Confirm the created resource is reachable/usable."""
        ...
