"""
conftest.py — Shared pytest fixtures using moto for all unit tests.
"""
from __future__ import annotations

import os

import boto3
import pytest

# Set mock AWS credentials before any boto3 calls
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("ENVIRONMENT_STATE_TABLE", "EnvironmentState")
os.environ.setdefault("SUBSCRIBERS_TABLE", "MarketplaceSubscribers")
os.environ.setdefault("AMPLIFY_APP_ID", "d246slprgvqfid")
os.environ.setdefault("SOURCE_ENV_NAME", "demo")
os.environ.setdefault("ACCOUNT_ID", "215116348101")


@pytest.fixture
def aws_credentials():
    """Fake AWS credentials so moto intercepts all boto3 calls."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture
def dynamodb_environment_state_table(aws_credentials):
    """Create the EnvironmentState DynamoDB table in moto."""
    from moto import mock_aws
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-central-1")
        table = ddb.create_table(
            TableName="EnvironmentState",
            KeySchema=[{"AttributeName": "environment_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "environment_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


@pytest.fixture
def dynamodb_subscribers_table(aws_credentials):
    """Create the MarketplaceSubscribers DynamoDB table in moto."""
    from moto import mock_aws
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-central-1")
        table = ddb.create_table(
            TableName="MarketplaceSubscribers",
            KeySchema=[{"AttributeName": "regToken", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "regToken", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


@pytest.fixture
def sample_subscriber():
    """Return a valid SubscriberModel for tests."""
    from src.common.models import SubscriberModel
    return SubscriberModel(
        reg_token="test-token-123",
        company_name="ACT International",
        contact_email="admin@act.com",
        contact_person="John Doe",
        contact_phone="+1234567890",
    )


@pytest.fixture
def sample_environment(sample_subscriber):
    """Return a valid EnvironmentModel for tests."""
    from src.common.models import EnvironmentModel
    env = EnvironmentModel(
        source_env_name="demo",
        target_env_name="act-international",
        region="eu-central-1",
        account_id="215116348101",
        amplify_app_id="d246slprgvqfid",
        reg_token=sample_subscriber.reg_token,
        contact_email=sample_subscriber.contact_email,
        company_name=sample_subscriber.company_name,
    )
    return env
