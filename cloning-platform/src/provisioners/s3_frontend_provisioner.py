"""
s3_frontend_provisioner.py — Deploys the Catalyst-Assess frontend to a
per-tenant S3 bucket by copying from the pre-built base assets bucket and
injecting a tenant-specific config.js at runtime.
"""
from __future__ import annotations

import json

from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import retry
from .base import BaseProvisioner


# The bucket that holds the pre-built base Assess bundle (uploaded once via
# scripts/build_and_upload_base.sh)
BASE_ASSETS_BUCKET = "catalyst-assess-base-assets-eu-central-1"


class S3FrontendProvisioner(BaseProvisioner):
    """
    Creates a dedicated S3 static-website bucket per tenant, copies the
    pre-built Catalyst-Assess frontend bundle, and injects a tenant-specific
    config.js so the app picks up the correct API endpoints at runtime.
    """

    resource_type = ResourceType.S3_FRONTEND

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        s3 = self.get_client("s3")
        bucket_name = self._bucket_name(env.target_env_name)

        # 1. Create the per-tenant bucket
        self._create_bucket(s3, bucket_name)

        # 2. Make it publicly readable
        self._configure_public_access(s3, bucket_name)

        # 3. Enable static website hosting
        self._enable_website(s3, bucket_name)

        # 4. Copy all base assets from the pre-built source bucket
        self._copy_base_assets(s3, bucket_name)

        # 5. Generate and upload the tenant-specific config.js
        config_js = self._build_config_js(env)
        self._upload_config(s3, bucket_name, config_js)

        website_url = (
            f"http://{bucket_name}.s3-website.{self.region}.amazonaws.com"
        )

        # 6. Persist URL back onto the environment so later steps & report can use it
        env.assess_url = website_url

        self.logger.info(
            "S3 frontend deployed",
            extra={"bucket": bucket_name, "url": website_url},
        )

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=bucket_name,
            target_arn=f"arn:aws:s3:::{bucket_name}",
            metadata={"url": website_url, "bucket": bucket_name},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _bucket_name(self, env_name: str) -> str:
        """Return a valid, unique S3 bucket name for this tenant."""
        import re
        safe = re.sub(r"[^a-z0-9-]", "-", env_name.lower())
        safe = re.sub(r"-+", "-", safe).strip("-")
        # S3 bucket names must be <= 63 chars
        return f"catalyst-assess-{safe}"[:63]

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_bucket(self, s3: object, bucket_name: str) -> None:
        """Create the S3 bucket (idempotent)."""
        try:
            if self.region == "us-east-1":
                s3.create_bucket(Bucket=bucket_name)  # type: ignore[attr-defined]
            else:
                s3.create_bucket(  # type: ignore[attr-defined]
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": self.region},
                )
            self.logger.info("S3 bucket created", extra={"bucket": bucket_name})
        except s3.exceptions.BucketAlreadyOwnedByYou:  # type: ignore[attr-defined]
            self.logger.info("S3 bucket already exists", extra={"bucket": bucket_name})

    def _configure_public_access(self, s3: object, bucket_name: str) -> None:
        """Disable the public-access block and attach a public-read policy."""
        s3.put_public_access_block(  # type: ignore[attr-defined]
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
            }],
        })
        s3.put_bucket_policy(Bucket=bucket_name, Policy=policy)  # type: ignore[attr-defined]
        self.logger.info("S3 bucket public policy applied", extra={"bucket": bucket_name})

    def _enable_website(self, s3: object, bucket_name: str) -> None:
        """Configure the bucket for static website hosting."""
        s3.put_bucket_website(  # type: ignore[attr-defined]
            Bucket=bucket_name,
            WebsiteConfiguration={
                "IndexDocument": {"Suffix": "index.html"},
                "ErrorDocument": {"Key": "index.html"},
            },
        )
        self.logger.info("S3 static website hosting enabled", extra={"bucket": bucket_name})

    def _copy_base_assets(self, s3: object, dest_bucket: str) -> None:
        """Copy every object from the base-assets bucket to the tenant bucket."""
        paginator = s3.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
        pages = paginator.paginate(Bucket=BASE_ASSETS_BUCKET)
        copied = 0
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Skip config.js — we generate a fresh tenant-specific one below
                if key == "config.js":
                    continue
                s3.copy_object(  # type: ignore[attr-defined]
                    CopySource={"Bucket": BASE_ASSETS_BUCKET, "Key": key},
                    Bucket=dest_bucket,
                    Key=key,
                )
                copied += 1
        self.logger.info(
            "Base assets copied to tenant bucket",
            extra={"bucket": dest_bucket, "files_copied": copied},
        )

    def _upload_config(self, s3: object, bucket_name: str, config_js: str) -> None:
        """Upload the generated tenant config.js."""
        s3.put_object(  # type: ignore[attr-defined]
            Bucket=bucket_name,
            Key="config.js",
            Body=config_js.encode("utf-8"),
            ContentType="application/javascript",
            CacheControl="no-cache,no-store,must-revalidate",
        )
        self.logger.info("Tenant config.js uploaded", extra={"bucket": bucket_name})

    def _build_config_js(self, env: EnvironmentModel) -> str:
        """
        Generate a runtime config.js that injects tenant-specific values into
        the browser's window.APP_CONFIG object.
        The Assess frontend reads these values at runtime via appConfig.ts.
        """

        def get_api_url(base_name: str) -> str:
            if base_name in env.api_urls:
                return env.api_urls[base_name]
            for key, url in env.api_urls.items():
                if key.startswith(base_name):
                    return url
            return ""

        staff_url = get_api_url("staffApi")
        backend_url = get_api_url("backendApi")
        org_id = f"org-{env.target_env_name}"

        # Retrieve the API key from Secrets Manager if available
        api_key = self._get_api_key(env)

        config = {
            "REST_API_URL": backend_url or staff_url,
            "STAFF_API_URL": staff_url,
            "API_KEY": api_key,
            "USER_POOL_ID": env.user_pool_id,
            "APP_CLIENT_ID": env.app_client_id,
            "IDENTITY_POOL_ID": env.identity_pool_id,
            "APPSYNC_ENDPOINT": env.appsync_graphql_url,
            "APPSYNC_API_KEY": env.appsync_api_key,
            "CLOUDFRONT_URI": env.cloudfront_url or "https://d1i0z2k8umbb0n.cloudfront.net",
            "ORG_ID": org_id,
            "REGION": self.region,
            "ENCRYPT_KEY": "9f2d4a7c3b1e5f8a6c0d9e743f12b6a8e4c5d7f9a0b3c2d1e6f8a7c9b0d4e3f",
            "FALLBACK_ORG": org_id,
        }

        lines = [f'  "{k}": "{v}"' for k, v in config.items()]
        return "window.APP_CONFIG = {\n" + ",\n".join(lines) + "\n};\n"

    def _get_api_key(self, env: EnvironmentModel) -> str:
        """Retrieve the API key from Secrets Manager (stored by APIGatewayProvisioner)."""
        try:
            sm = self.get_client("secretsmanager")
            resp = sm.get_secret_value(SecretId=env.secret_name)  # type: ignore[attr-defined]
            import json as _json
            payload = _json.loads(resp.get("SecretString", "{}"))
            return payload.get("api_key", "")
        except Exception:
            return ""

    def validate(self, record: ResourceRecord) -> bool:
        return bool(record.target_id)
