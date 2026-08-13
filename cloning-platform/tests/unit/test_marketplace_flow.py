"""
test_marketplace_flow.py — Unit tests for subscriber persistence and Marketplace landing flow.
"""
from __future__ import annotations

import json

from src.handlers import marketplace_landing, marketplace_subscriber
from src.state.subscriber_state_manager import SubscriberStateManager


def test_subscriber_state_manager_persists_legacy_schema(
    dynamodb_subscribers_table,
    sample_subscriber,
):
    manager = SubscriberStateManager("MarketplaceSubscribers", region="eu-central-1")

    manager.put(sample_subscriber)
    stored = dynamodb_subscribers_table.scan()["Items"][0]

    assert stored["regToken"] == sample_subscriber.reg_token
    assert stored["companyName"] == sample_subscriber.company_name
    assert stored["contactEmail"] == sample_subscriber.contact_email
    assert stored["isDeployed"] is False

    pending = manager.list_pending()
    assert len(pending) == 1
    assert pending[0].reg_token == sample_subscriber.reg_token

    manager.mark_active(sample_subscriber.reg_token, "env-123")
    updated = dynamodb_subscribers_table.get_item(Key={"regToken": sample_subscriber.reg_token})["Item"]
    assert updated["isDeployed"] is True
    assert updated["environmentId"] == "env-123"


def test_parse_subscriber_accepts_camel_case_payload():
    subscriber = marketplace_subscriber._parse_subscriber(
        {
            "regToken": "legacy-token",
            "companyName": "Legacy Co",
            "contactEmail": "admin@legacy.co",
        }
    )

    assert subscriber.reg_token == "legacy-token"
    assert subscriber.company_name == "Legacy Co"
    assert subscriber.contact_email == "admin@legacy.co"


def test_marketplace_register_handler_resolves_token_and_starts_subscriber_flow(monkeypatch):
    captured = {}

    def fake_resolve(token: str) -> dict[str, str]:
        assert token == "marketplace-token"
        return {
            "customer_identifier": "cust-123",
            "product_code": "prod-001",
            "customer_aws_account_id": "123456789012",
        }

    def fake_subscriber_handler(event, context):
        captured["payload"] = json.loads(event["body"])
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Provisioning started"}),
        }

    monkeypatch.setattr(marketplace_landing, "_resolve_customer", fake_resolve)
    monkeypatch.setattr(marketplace_landing.marketplace_subscriber, "handler", fake_subscriber_handler)

    response = marketplace_landing.register_handler(
        {
            "httpMethod": "POST",
            "body": json.dumps(
                {
                    "marketplace_token": "marketplace-token",
                    "company_name": "Acme Corp",
                    "contact_email": "admin@acme.com",
                    "contact_person": "Jamie",
                    "contact_phone": "+1-202-555-0100",
                }
            ),
        },
        None,
    )

    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert captured["payload"]["reg_token"] == "cust-123"
    assert captured["payload"]["company_name"] == "Acme Corp"
    assert captured["payload"]["contact_email"] == "admin@acme.com"
    assert body["marketplace"]["product_code"] == "prod-001"
