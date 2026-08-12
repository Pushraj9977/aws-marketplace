"""
test_models.py — Unit tests for Pydantic v2 data models.
"""
import pytest
from src.common.models import EnvironmentModel, ResourceRecord, SubscriberModel
from src.common.constants import ResourceStatus, ResourceType


class TestSubscriberModel:
    def test_valid_subscriber(self):
        sub = SubscriberModel(
            reg_token="tok123",
            company_name="ACME Corp",
            contact_email="admin@acme.com",
        )
        assert sub.reg_token == "tok123"
        assert sub.contact_email == "admin@acme.com"

    def test_email_normalized_to_lowercase(self):
        sub = SubscriberModel(
            reg_token="tok",
            company_name="X",
            contact_email="ADMIN@ACME.COM",
        )
        assert sub.contact_email == "admin@acme.com"

    def test_invalid_email_raises(self):
        with pytest.raises(Exception):
            SubscriberModel(reg_token="t", company_name="X", contact_email="not-an-email")

    def test_empty_company_name_raises(self):
        with pytest.raises(Exception):
            SubscriberModel(reg_token="t", company_name="   ", contact_email="a@b.com")

    def test_sanitized_env_name(self):
        sub = SubscriberModel(
            reg_token="t", company_name="My Company Ltd.", contact_email="a@b.com"
        )
        name = sub.sanitized_env_name()
        assert " " not in name
        assert "." not in name
        assert name == name.lower()


class TestEnvironmentModel:
    def test_secret_name_auto_set(self):
        env = EnvironmentModel(
            source_env_name="demo",
            target_env_name="acme",
            region="eu-central-1",
            account_id="123456789012",
        )
        assert env.secret_name == "acme/app-secret"

    def test_add_and_get_resource(self):
        env = EnvironmentModel(
            source_env_name="demo",
            target_env_name="acme",
            region="eu-central-1",
            account_id="123",
        )
        record = ResourceRecord(
            resource_type=ResourceType.DYNAMODB_TABLE,
            source_id="demo",
            target_id="acme-table",
            status=ResourceStatus.DONE,
        )
        env.add_resource(record)
        fetched = env.get_resource(ResourceType.DYNAMODB_TABLE, "demo")
        assert fetched is not None
        assert fetched.target_id == "acme-table"

    def test_all_resources_done(self):
        env = EnvironmentModel(
            source_env_name="demo",
            target_env_name="acme",
            region="eu-central-1",
            account_id="123",
        )
        env.add_resource(ResourceRecord(
            resource_type=ResourceType.DYNAMODB_TABLE,
            source_id="demo",
            status=ResourceStatus.DONE,
        ))
        assert env.all_resources_done() is True

    def test_not_all_resources_done(self):
        env = EnvironmentModel(
            source_env_name="demo",
            target_env_name="acme",
            region="eu-central-1",
            account_id="123",
        )
        env.add_resource(ResourceRecord(
            resource_type=ResourceType.DYNAMODB_TABLE,
            source_id="demo",
            status=ResourceStatus.PENDING,
        ))
        assert env.all_resources_done() is False
