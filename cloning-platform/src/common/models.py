"""
models.py — Pydantic v2 data models for the cloning platform.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import EnvironmentStatus, ResourceStatus, ResourceType


# ---------------------------------------------------------------------------
# Resource Record
# ---------------------------------------------------------------------------

class ResourceRecord(BaseModel):
    """Tracks the state of one cloned AWS resource."""

    model_config = ConfigDict(use_enum_values=True)

    resource_type: ResourceType
    source_id: str
    target_id: str = ""
    target_arn: str = ""
    status: ResourceStatus = ResourceStatus.PENDING
    error_message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Subscriber Model
# ---------------------------------------------------------------------------

class SubscriberModel(BaseModel):
    """Represents a row in the MarketplaceSubscribers DynamoDB table."""

    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)

    reg_token: str = Field(
        ...,
        description="Primary key — unique registration token from Marketplace",
        validation_alias=AliasChoices("reg_token", "regToken"),
    )
    company_name: str = Field(validation_alias=AliasChoices("company_name", "companyName"))
    contact_email: str = Field(validation_alias=AliasChoices("contact_email", "contactEmail"))
    contact_person: str = Field(default="", validation_alias=AliasChoices("contact_person", "contactPerson"))
    contact_phone: str = Field(default="", validation_alias=AliasChoices("contact_phone", "contactPhone"))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        validation_alias=AliasChoices("created_at", "createdAt"),
    )
    is_deployed: bool = Field(default=False, validation_alias=AliasChoices("is_deployed", "isDeployed"))
    status: EnvironmentStatus = EnvironmentStatus.PENDING
    target_env_name: str = Field(default="", validation_alias=AliasChoices("target_env_name", "targetEnvName"))
    environment_id: str = Field(default="", validation_alias=AliasChoices("environment_id", "environmentId"))

    @field_validator("company_name")
    @classmethod
    def company_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("company_name must not be blank")
        return v.strip()

    @field_validator("contact_email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError(f"Invalid email: {v}")
        return v.lower().strip()

    def sanitized_env_name(self) -> str:
        """Return a valid AWS-resource-name-safe version of company_name."""
        import re
        name = self.company_name.lower()
        name = re.sub(r"[^a-z0-9]", "-", name)
        name = re.sub(r"-+", "-", name).strip("-")
        return name[:40]  # AWS names max 64 chars; keep short for prefixing


# ---------------------------------------------------------------------------
# Environment Model
# ---------------------------------------------------------------------------

class EnvironmentModel(BaseModel):
    """Represents the full state of one clone operation."""

    model_config = ConfigDict(use_enum_values=True)

    environment_id: str = Field(default_factory=lambda: str(uuid4()))
    source_env_name: str
    target_env_name: str
    region: str
    account_id: str
    amplify_app_id: str = ""
    status: EnvironmentStatus = EnvironmentStatus.STARTED
    resources: dict[str, ResourceRecord] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    reg_token: str = ""
    contact_email: str = ""
    company_name: str = ""

    # Collected ARNs/IDs that provisioners inject after creation
    iam_role_arn: str = ""
    user_pool_id: str = ""
    app_client_id: str = ""
    identity_pool_id: str = ""
    secret_name: str = ""
    api_urls: dict[str, str] = Field(default_factory=dict)
    appsync_api_id: str = ""
    appsync_graphql_url: str = ""
    appsync_api_key: str = ""
    admin_email: str = ""
    admin_password: str = ""
    admin_credentials_secret_name: str = ""
    # Infrastructure fields for full tenant isolation (Audit 3)
    s3_bucket_name: str = ""
    cloudfront_url: str = ""
    dynamodb_table_names: dict[str, str] = Field(default_factory=dict)
    lambda_function_arns: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_secret_name(self) -> "EnvironmentModel":
        if not self.secret_name:
            self.secret_name = f"{self.target_env_name}/app-secret"
        return self

    def add_resource(self, record: ResourceRecord) -> None:
        # resource_type is stored as a string value due to use_enum_values=True
        rt = record.resource_type if isinstance(record.resource_type, str) else record.resource_type.value
        key = f"{rt}:{record.source_id}"
        self.resources[key] = record

    def get_resource(self, resource_type: ResourceType, source_id: str) -> ResourceRecord | None:
        key = f"{resource_type.value}:{source_id}"
        return self.resources.get(key)

    def all_resources_done(self) -> bool:
        return all(r.status == ResourceStatus.DONE for r in self.resources.values())


# ---------------------------------------------------------------------------
# Health Check Result
# ---------------------------------------------------------------------------

class HealthCheckResult(BaseModel):
    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Step Functions event payloads
# ---------------------------------------------------------------------------

class ProvisionerInput(BaseModel):
    """Input payload for every provisioner Lambda."""

    environment_id: str
    source_env_name: str
    target_env_name: str
    region: str
    account_id: str
    amplify_app_id: str = ""
    reg_token: str = ""
    contact_email: str = ""
    company_name: str = ""


class ProvisionerOutput(BaseModel):
    """Output payload from every provisioner Lambda."""

    environment_id: str
    success: bool
    resource_type: str
    target_id: str = ""
    target_arn: str = ""
    error_message: str = ""
    updated_env: dict[str, Any] = Field(default_factory=dict)
