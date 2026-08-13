"""
marketplace_subscriber.py — Lambda handler for Marketplace subscription events.

Triggered by:
  - AWS Marketplace SQS subscription events
  - SaaS Landing Page API calls (POST /register)

Responsibilities:
  1. Parse and validate the incoming subscriber payload.
  2. Write the subscriber to MarketplaceSubscribers DynamoDB.
  3. Start the Step Functions clone pipeline.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3

from ..common.config import get_config
from ..common.exceptions import ValidationError
from ..common.logger import get_logger
from ..common.models import SubscriberModel, EnvironmentModel
from ..state.subscriber_state_manager import SubscriberStateManager
from ..state.environment_state_manager import EnvironmentStateManager

logger = get_logger(__name__)
config = get_config()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda entry point for Marketplace subscription events.

    Args:
        event: SQS message body or direct API Gateway payload.
        context: Lambda context object.

    Returns:
        HTTP-compatible response dict.
    """
    logger.info("MarketplaceSubscriberHandler invoked")

    try:
        payload = _extract_payload(event)
        subscriber = _parse_subscriber(payload)

        state_mgr = SubscriberStateManager(
            table_name=config.subscribers_table,
            region=config.region,
        )
        state_mgr.put(subscriber)
        logger.info(
            "Subscriber written to DB",
            extra={"reg_token": subscriber.reg_token},
        )

        execution_arn = _start_pipeline(subscriber)
        logger.info(
            "Step Functions execution started",
            extra={"execution_arn": execution_arn},
        )

        return {
            "statusCode": 200,
            "headers": _cors_headers(),
            "body": json.dumps({
                "message": "Provisioning started",
                "reg_token": subscriber.reg_token,
                "execution_arn": execution_arn,
            }),
        }

    except ValidationError as exc:
        logger.error("Validation error: %s", exc.message)
        return {"statusCode": 400, "headers": _cors_headers(), "body": json.dumps({"error": exc.message})}
    except Exception as exc:
        logger.error("Unhandled error: %s", str(exc))
        return {"statusCode": 500, "headers": _cors_headers(), "body": json.dumps({"error": str(exc)})}


def _extract_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Handle SQS, API Gateway, and direct invocation event formats."""
    # SQS batch
    if "Records" in event:
        body = event["Records"][0].get("body", "{}")
        return json.loads(body) if isinstance(body, str) else body

    # API Gateway HTTP
    if "body" in event:
        body = event["body"]
        return json.loads(body) if isinstance(body, str) else body

    return event


def _parse_subscriber(payload: dict[str, Any]) -> SubscriberModel:
    """Validate and parse the subscriber payload."""
    payload = _normalize_payload(payload)
    required = ["reg_token", "company_name", "contact_email"]
    missing = [f for f in required if not payload.get(f)]
    if missing:
        raise ValidationError(f"Missing required fields: {missing}")

    try:
        return SubscriberModel(**payload)
    except Exception as exc:
        raise ValidationError(f"Invalid subscriber data: {exc}") from exc


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    field_map = {
        "regToken": "reg_token",
        "companyName": "company_name",
        "contactEmail": "contact_email",
        "contactPerson": "contact_person",
        "contactPhone": "contact_phone",
    }
    for legacy_key, canonical_key in field_map.items():
        if legacy_key in normalized and canonical_key not in normalized:
            normalized[canonical_key] = normalized[legacy_key]
    return normalized


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "OPTIONS,POST",
    }


def _start_pipeline(subscriber: SubscriberModel) -> str:
    """Start the Step Functions clone pipeline for this subscriber."""
    sf_client = boto3.client("stepfunctions", region_name=config.region)
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]

    target_env = subscriber.sanitized_env_name()

    input_payload = {
        "reg_token": subscriber.reg_token,
        "company_name": subscriber.company_name,
        "contact_email": subscriber.contact_email,
        "source_env_name": config.source_env_name,
        "target_env_name": target_env,
        "region": config.region,
        "account_id": config.account_id,
        "amplify_app_id": config.amplify_app_id,
    }

    env_model = EnvironmentModel(**input_payload)
    env_state_mgr = EnvironmentStateManager(
        table_name=os.environ.get("STATE_TABLE", "EnvironmentState"),
        region=config.region,
    )
    env_state_mgr.create(env_model)

    resp = sf_client.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"clone-{target_env}-{subscriber.reg_token[:8]}",
        input=json.dumps({"environment": env_model.model_dump(mode="json")}),
    )
    return resp["executionArn"]
