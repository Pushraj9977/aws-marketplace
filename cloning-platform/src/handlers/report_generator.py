"""
report_generator.py — Lambda handler that generates HTML + JSON reports on completion.
Uploads to S3 and publishes to SNS for customer + admin notification.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import boto3

from ..common.config import get_config
from ..common.logger import get_logger
from ..common.models import EnvironmentModel
from ..common.constants import EnvironmentStatus
from ..reports.html_renderer import HTMLRenderer
from ..reports.json_reporter import JSONReporter
from ..state.environment_state_manager import EnvironmentStateManager
from ..state.subscriber_state_manager import SubscriberStateManager

logger = get_logger(__name__)
config = get_config()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda entry point for report generation.

    Triggered by Step Functions after successful health check.

    Args:
        event: Contains environment_id.
        context: Lambda context.

    Returns:
        { "html_url": str, "json_url": str }
    """
    env_data = event.get("environment", {})
    environment_id = env_data.get("environment_id", "")
    logger.info("ReportGenerator invoked", extra={"environment_id": environment_id})

    state_mgr = EnvironmentStateManager(
        table_name=config.environment_state_table,
        region=config.region,
    )
    sub_mgr = SubscriberStateManager(
        table_name=config.subscribers_table,
        region=config.region,
    )

    env = state_mgr.get(environment_id)
    html_url, json_url = _generate_and_upload(env)

    # Mark subscriber as ACTIVE
    if env.reg_token:
        sub_mgr.mark_active(env.reg_token, environment_id)
        state_mgr.update_status(environment_id, EnvironmentStatus.ACTIVE)

    # Publish notification
    _publish_notification(env, html_url, json_url)

    return {"html_url": html_url, "json_url": json_url}


def _generate_and_upload(env: EnvironmentModel) -> tuple[str, str]:
    """Render both report formats and upload to S3."""
    s3 = boto3.client("s3", region_name=config.region)
    bucket = config.report_s3_bucket
    prefix = f"reports/{env.environment_id}"

    # HTML Report
    html_content = HTMLRenderer().render(env)
    html_key = f"{prefix}/report.html"
    if bucket:
        s3.put_object(
            Bucket=bucket,
            Key=html_key,
            Body=html_content.encode("utf-8"),
            ContentType="text/html",
        )
        html_url = f"https://{bucket}.s3.{config.region}.amazonaws.com/{html_key}"
    else:
        html_url = "s3-not-configured"

    # JSON Report
    json_content = JSONReporter().generate(env)
    json_key = f"{prefix}/report.json"
    if bucket:
        s3.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json.dumps(json_content, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        json_url = f"https://{bucket}.s3.{config.region}.amazonaws.com/{json_key}"
    else:
        json_url = "s3-not-configured"

    logger.info(
        "Reports uploaded",
        extra={"environment_id": env.environment_id, "html_url": html_url},
    )
    return html_url, json_url


def _publish_notification(
    env: EnvironmentModel, html_url: str, json_url: str
) -> None:
    """Publish success notification via SNS."""
    topic_arn = config.notification_topic_arn
    if not topic_arn:
        logger.warning("No SNS topic configured — skipping notification")
        return

    sns = boto3.client("sns", region_name=config.region)
    message = (
        f"✅ Environment '{env.target_env_name}' successfully provisioned!\n\n"
        f"Company:        {env.company_name}\n"
        f"Environment ID: {env.environment_id}\n"
        f"Completed At:   {datetime.now(timezone.utc).isoformat()}\n\n"
        f"HTML Report: {html_url}\n"
        f"JSON Report: {json_url}\n"
    )
    sns.publish(
        TopicArn=topic_arn,
        Subject=f"[CloningPlatform] Environment {env.target_env_name} is ACTIVE",
        Message=message,
    )
    logger.info("SNS notification published", extra={"topic": topic_arn})
