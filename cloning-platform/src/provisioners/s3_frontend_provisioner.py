"""
s3_frontend_provisioner.py — Deploys the Catalyst-Assess frontend to a
per-tenant S3 bucket by copying from the pre-built base assets bucket and
injecting a tenant-specific config.js at runtime.

CloudFront is provisioned automatically in front of every tenant bucket so
customers always receive an HTTPS URL (*.cloudfront.net cert is free and
automatic — no ACM setup required).
"""
from __future__ import annotations

import json
import time
import uuid

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
        s3 = self.get_target_client("s3")
        bucket_name = self._bucket_name(env.target_env_name)

        # 1. Create the per-tenant bucket
        self._create_bucket(s3, bucket_name)

        # 2. Make it publicly readable (CloudFront still needs this for website origin)
        self._configure_public_access(s3, bucket_name)

        # 3. Enable static website hosting
        self._enable_website(s3, bucket_name)

        # 4. Copy all base assets from the pre-built source bucket
        self._copy_base_assets(s3, bucket_name)

        # 5. Create CloudFront distribution for HTTPS (uses free *.cloudfront.net cert)
        s3_website_origin = (
            f"{bucket_name}.s3-website.{self.target_region}.amazonaws.com"
        )
        cf_domain, cf_distribution_id = self._create_cloudfront_distribution(
            env.target_env_name, s3_website_origin
        )
        https_url = f"https://{cf_domain}"

        # 6. Generate and upload tenant-specific config.js (now includes HTTPS URL)
        env.assess_url = https_url
        config_js = self._build_config_js(env)
        self._upload_config(s3, bucket_name, config_js)

        self.logger.info(
            "S3 frontend deployed with HTTPS via CloudFront",
            extra={"bucket": bucket_name, "url": https_url, "cf_id": cf_distribution_id},
        )

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=bucket_name,
            target_arn=f"arn:aws:s3:::{bucket_name}",
            metadata={
                "url": https_url,
                "bucket": bucket_name,
                "cloudfront_domain": cf_domain,
                "cloudfront_distribution_id": cf_distribution_id,
            },
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

    @retry(max_attempts=3, delay_seconds=5.0)
    def _create_cloudfront_distribution(
        self, env_name: str, s3_website_origin: str
    ) -> tuple[str, str]:
        """
        Create (or reuse) a CloudFront distribution in front of the tenant S3
        website bucket.  Returns (domain_name, distribution_id).

        CloudFront distributions come with a free *.cloudfront.net HTTPS cert —
        no ACM setup needed. The distribution uses the S3 *website* endpoint
        as origin so SPA routing (404 → index.html) works correctly.
        """
        # CloudFront is a global service — its API endpoint is always us-east-1
        import boto3 as _boto3
        cf = _boto3.client("cloudfront", region_name="us-east-1")

        # Idempotency: check if a distribution for this origin already exists
        existing = self._find_existing_cf_distribution(cf, s3_website_origin)
        if existing:
            self.logger.info(
                "Reusing existing CloudFront distribution",
                extra={"domain": existing[0], "id": existing[1]},
            )
            return existing

        caller_ref = f"{env_name}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        origin_id = f"S3-assess-{env_name}"

        resp = cf.create_distribution_with_tags(  # type: ignore[attr-defined]
            DistributionConfigWithTags={
                "DistributionConfig": {
                    "CallerReference": caller_ref,
                    "Comment": f"Catalyst Assess app — {env_name}",
                    "Enabled": True,
                    "Origins": {
                        "Quantity": 1,
                        "Items": [{
                            "Id": origin_id,
                            "DomainName": s3_website_origin,
                            "CustomOriginConfig": {
                                # S3 website endpoints speak plain HTTP on port 80
                                "HTTPPort": 80,
                                "HTTPSPort": 443,
                                "OriginProtocolPolicy": "http-only",
                            },
                        }],
                    },
                    "DefaultCacheBehavior": {
                        "TargetOriginId": origin_id,
                        "ViewerProtocolPolicy": "redirect-to-https",
                        "AllowedMethods": {
                            "Quantity": 2,
                            "Items": ["GET", "HEAD"],
                            "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
                        },
                        # CachingOptimized managed policy — do NOT mix with ForwardedValues/MinTTL
                        "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
                        "Compress": True,
                    },
                    # SPA routing: send all errors back to index.html
                    "CustomErrorResponses": {
                        "Quantity": 1,
                        "Items": [{
                            "ErrorCode": 403,
                            "ResponseCode": "200",
                            "ResponsePagePath": "/index.html",
                            "ErrorCachingMinTTL": 10,
                        }],
                    },
                    "PriceClass": "PriceClass_100",  # US + Europe + Asia — cheapest tier
                    "HttpVersion": "http2",
                },
                # Tags must be a top-level sibling of DistributionConfig, not nested inside it
                "Tags": {
                    "Items": [
                        {"Key": "Environment", "Value": env_name},
                        {"Key": "ManagedBy", "Value": "CloningPlatform"},
                    ]
                },
            }
        )

        dist = resp["Distribution"]
        domain = dist["DomainName"]
        dist_id = dist["Id"]
        self.logger.info(
            "CloudFront distribution created (deploying globally — may take 5-15 min)",
            extra={"domain": domain, "id": dist_id},
        )
        return domain, dist_id

    def _find_existing_cf_distribution(
        self, cf: object, origin_domain: str
    ) -> tuple[str, str] | None:
        """Return (domain, id) if a distribution already points at this S3 origin."""
        try:
            paginator = cf.get_paginator("list_distributions")  # type: ignore[attr-defined]
            for page in paginator.paginate():
                items = page.get("DistributionList", {}).get("Items", [])
                for dist in items:
                    origins = dist.get("Origins", {}).get("Items", [])
                    for origin in origins:
                        if origin.get("DomainName", "") == origin_domain:
                            return dist["DomainName"], dist["Id"]
        except Exception as e:
            self.logger.warning(f"Could not check existing CF distributions: {e}")
        return None

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_bucket(self, s3: object, bucket_name: str) -> None:
        """Create the S3 bucket (idempotent)."""
        try:
            if self.target_region == "us-east-1":
                s3.create_bucket(Bucket=bucket_name)  # type: ignore[attr-defined]
            else:
                s3.create_bucket(  # type: ignore[attr-defined]
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": self.target_region},
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
            "REGION": self.target_region,
            "ENCRYPT_KEY": "9f2d4a7c3b1e5f8a6c0d9e743f12b6a8e4c5d7f9a0b3c2d1e6f8a7c9b0d4e3f",
            "FALLBACK_ORG": org_id,
            # ASSESS_URL: the public HTTPS URL of this tenant's Assess app
            "ASSESS_URL": env.assess_url or "",
        }

        lines = [f'  "{k}": "{v}"' for k, v in config.items()]
        return "window.APP_CONFIG = {\n" + ",\n".join(lines) + "\n};\n"

    def _get_api_key(self, env: EnvironmentModel) -> str:
        """Retrieve the API key from Secrets Manager (stored by APIGatewayProvisioner)."""
        try:
            sm = self.get_target_client("secretsmanager")
            resp = sm.get_secret_value(SecretId=env.secret_name)  # type: ignore[attr-defined]
            import json as _json
            payload = _json.loads(resp.get("SecretString", "{}"))
            return payload.get("api_key", "")
        except Exception:
            return ""

    def validate(self, record: ResourceRecord) -> bool:
        return bool(record.target_id)
