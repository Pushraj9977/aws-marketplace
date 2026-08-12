"""
subscriber_state_manager.py — CRUD for the MarketplaceSubscribers DynamoDB table.
"""
from __future__ import annotations

from datetime import datetime, timezone

import boto3

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
            item = subscriber.model_dump(mode="json")
            item["created_at"] = subscriber.created_at.isoformat()
            
            # Map snake_case to legacy camelCase DynamoDB schema
            item["regToken"] = item.pop("reg_token")

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
            
            # Map back to snake_case for Pydantic
            if "regToken" in item:
                item["reg_token"] = item.pop("regToken")
                
            return SubscriberModel.model_validate(item)
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
                    "SET is_deployed = :d, #s = :s, environment_id = :e, deployed_at = :t"
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
                FilterExpression="is_deployed = :v",
                ExpressionAttributeValues={":v": False},
            )
            subscribers = []
            for item in resp.get("Items", []):
                if "regToken" in item:
                    item["reg_token"] = item.pop("regToken")
                subscribers.append(SubscriberModel.model_validate(item))
            return subscribers
        except Exception as exc:
            raise StateManagerError(f"Failed to list pending subscribers: {exc}") from exc
