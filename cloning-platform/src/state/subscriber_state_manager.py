"""
subscriber_state_manager.py — CRUD for the MarketplaceSubscribers DynamoDB table.
"""
from __future__ import annotations

from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr

from ..common.constants import EnvironmentStatus
from ..common.exceptions import StateManagerError, SubscriberNotFoundError
from ..common.logger import get_logger
from ..common.models import SubscriberModel

logger = get_logger(__name__)


class SubscriberStateManager:
    """
    Repository for all MarketplaceSubscribers DynamoDB operations.

    Table schema:
        PK: reg_token (S)
    """

    def __init__(self, table_name: str, region: str = "eu-central-1") -> None:
        self.table_name = table_name
        self._ddb = boto3.resource("dynamodb", region_name=region)
        self._table = self._ddb.Table(table_name)

    def put(self, subscriber: SubscriberModel) -> None:
        """
        Write a new subscriber record. Fails if reg_token already exists.

        Args:
            subscriber: SubscriberModel to persist.

        Raises:
            StateManagerError: On DynamoDB write failure.
        """
        try:
            item = self._to_item(subscriber)

            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(regToken)",
            )
            logger.info("Subscriber created", extra={"reg_token": subscriber.reg_token})
        except self._ddb.meta.client.exceptions.ConditionalCheckFailedException:
            raise StateManagerError(
                f"Subscriber already exists: {subscriber.reg_token}",
                resource_id=subscriber.reg_token,
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to put subscriber: {exc}") from exc

    def get(self, reg_token: str) -> SubscriberModel:
        """
        Fetch a subscriber by registration token.

        Args:
            reg_token: The primary key.

        Returns:
            SubscriberModel instance.

        Raises:
            SubscriberNotFoundError: If not found.
        """
        try:
            resp = self._table.get_item(Key={"regToken": reg_token})
            item = resp.get("Item")
            if not item:
                raise SubscriberNotFoundError(
                    f"Subscriber not found: {reg_token}", resource_id=reg_token
                )

            return self._from_item(item)
        except SubscriberNotFoundError:
            raise
        except Exception as exc:
            raise StateManagerError(f"Failed to get subscriber: {exc}") from exc

    def mark_active(self, reg_token: str, environment_id: str) -> None:
        """
        Mark a subscriber as successfully deployed and ACTIVE.

        Args:
            reg_token: The subscriber's primary key.
            environment_id: The UUID of the completed clone environment.
        """
        try:
            self._table.update_item(
                Key={"regToken": reg_token},
                UpdateExpression=(
                    "SET isDeployed = :d, #s = :s, environmentId = :e, deployedAt = :t"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":d": True,
                    ":s": EnvironmentStatus.ACTIVE.value,
                    ":e": environment_id,
                    ":t": datetime.now(timezone.utc).isoformat(),
                },
            )
            logger.info(
                "Subscriber marked ACTIVE",
                extra={"reg_token": reg_token, "environment_id": environment_id},
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to mark subscriber active: {exc}") from exc

    def mark_failed(self, reg_token: str, reason: str) -> None:
        """Mark a subscriber deployment as FAILED."""
        try:
            self._table.update_item(
                Key={"regToken": reg_token},
                UpdateExpression="SET #s = :s, failure_reason = :r, failed_at = :t",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": EnvironmentStatus.FAILED.value,
                    ":r": reason,
                    ":t": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            raise StateManagerError(f"Failed to mark subscriber failed: {exc}") from exc

    def list_pending(self) -> list[SubscriberModel]:
        """
        Scan for all subscribers with is_deployed = false.

        Returns:
            List of pending SubscriberModel instances.
        """
        try:
            resp = self._table.scan(
                FilterExpression=(
                    Attr("isDeployed").eq(False)
                    | Attr("isDeployed").eq("false")
                    | Attr("status").eq(EnvironmentStatus.PENDING.value)
                ),
            )
            subscribers = []
            for item in resp.get("Items", []):
                subscriber = self._from_item(item)
                if not subscriber.is_deployed:
                    subscribers.append(subscriber)
            return subscribers
        except Exception as exc:
            raise StateManagerError(f"Failed to list pending subscribers: {exc}") from exc

    def _to_item(self, subscriber: SubscriberModel) -> dict:
        return {
            "regToken": subscriber.reg_token,
            "companyName": subscriber.company_name,
            "contactEmail": subscriber.contact_email,
            "contactPerson": subscriber.contact_person,
            "contactPhone": subscriber.contact_phone,
            "createdAt": subscriber.created_at.isoformat(),
            "isDeployed": subscriber.is_deployed,
            "status": subscriber.status,
            "targetEnvName": subscriber.target_env_name,
            "environmentId": subscriber.environment_id,
        }

    def _from_item(self, item: dict) -> SubscriberModel:
        normalized = dict(item)
        if "createdAt" in normalized and "created_at" not in normalized:
            normalized["created_at"] = normalized["createdAt"]
        if "regToken" in normalized and "reg_token" not in normalized:
            normalized["reg_token"] = normalized["regToken"]
        if "companyName" in normalized and "company_name" not in normalized:
            normalized["company_name"] = normalized["companyName"]
        if "contactEmail" in normalized and "contact_email" not in normalized:
            normalized["contact_email"] = normalized["contactEmail"]
        if "contactPerson" in normalized and "contact_person" not in normalized:
            normalized["contact_person"] = normalized["contactPerson"]
        if "contactPhone" in normalized and "contact_phone" not in normalized:
            normalized["contact_phone"] = normalized["contactPhone"]
        if "isDeployed" in normalized and "is_deployed" not in normalized:
            normalized["is_deployed"] = normalized["isDeployed"]
        if "targetEnvName" in normalized and "target_env_name" not in normalized:
            normalized["target_env_name"] = normalized["targetEnvName"]
        if "environmentId" in normalized and "environment_id" not in normalized:
            normalized["environment_id"] = normalized["environmentId"]
        return SubscriberModel.model_validate(normalized)
