"""
marketplace_landing.py — Backend endpoints for the AWS Marketplace SaaS landing flow.
"""
from __future__ import annotations

import json
from typing import Any

import boto3

from ..common.logger import get_logger
from . import marketplace_subscriber

logger = get_logger(__name__)


def resolve_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validate the Marketplace registration token and return the resolved customer."""
    if _http_method(event) == "OPTIONS":
        return _response(200, {"ok": True})

    try:
        token = _extract_marketplace_token(event)
        if not token:
            return _response(400, {"error": "Missing x-amzn-marketplace-token"})

        resolved = _resolve_customer(token)
        return _response(
            200,
            {
                "message": "Marketplace subscription verified",
                "customer": resolved,
            },
        )
    except Exception as exc:
        logger.error("Failed to resolve Marketplace customer: %s", exc)
        return _response(500, {"error": str(exc)})


def register_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Resolve the Marketplace token, normalize the registration payload, and start provisioning."""
    if _http_method(event) == "OPTIONS":
        return _response(200, {"ok": True})

    payload = _extract_payload(event)
    token = _extract_marketplace_token(event, payload)
    if not token:
        return _response(400, {"error": "Missing x-amzn-marketplace-token"})

    company_name = payload.get("company_name") or payload.get("companyName")
    contact_email = payload.get("contact_email") or payload.get("contactEmail")
    if not company_name or not contact_email:
        return _response(
            400,
            {"error": "company_name and contact_email are required"},
        )

    try:
        resolved = _resolve_customer(token)
        subscriber_payload = {
            "reg_token": resolved["customer_identifier"],
            "company_name": company_name,
            "contact_email": contact_email,
            "contact_person": payload.get("contact_person") or payload.get("contactPerson", ""),
            "contact_phone": payload.get("contact_phone") or payload.get("contactPhone", ""),
        }
        result = marketplace_subscriber.handler(
            {"body": json.dumps(subscriber_payload)},
            context,
        )
        result["headers"] = _cors_headers()
        body = json.loads(result.get("body", "{}"))
        body["marketplace"] = resolved
        result["body"] = json.dumps(body)
        return result
    except Exception as exc:
        logger.error("Marketplace registration failed: %s", exc)
        return _response(500, {"error": str(exc)})


def _extract_payload(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body", {})
    if isinstance(body, str):
        return json.loads(body or "{}")
    return body or {}


def _extract_marketplace_token(event: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    payload = payload or _extract_payload(event)
    query = event.get("queryStringParameters") or {}
    return (
        payload.get("marketplace_token")
        or payload.get("x-amzn-marketplace-token")
        or query.get("marketplace_token")
        or query.get("x-amzn-marketplace-token")
        or ""
    )


def _resolve_customer(token: str) -> dict[str, str]:
    # Bypass real AWS Marketplace resolution for simulation testing
    if token.startswith("test-"):
        return {
            "customer_identifier": token,
            "product_code": "test-product-code",
            "customer_aws_account_id": "000000000000",
        }
        
    client = boto3.client("meteringmarketplace")
    response = client.resolve_customer(RegistrationToken=token)
    return {
        "customer_identifier": response.get("CustomerIdentifier", ""),
        "product_code": response.get("ProductCode", ""),
        "customer_aws_account_id": response.get("CustomerAWSAccountId", ""),
    }


def _http_method(event: dict[str, Any]) -> str:
    if "httpMethod" in event:
        return str(event["httpMethod"]).upper()
    request_context = event.get("requestContext", {})
    http = request_context.get("http", {})
    return str(http.get("method", "")).upper()


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps(body),
    }


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "OPTIONS,POST",
        "Content-Type": "application/json",
    }
