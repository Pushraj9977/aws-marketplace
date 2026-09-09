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

    # Publish admin notification via SNS
    _publish_notification(env, html_url, json_url)

    # Send customer welcome email via SES
    _send_customer_welcome_email(env, html_url)

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


def _send_customer_welcome_email(env: EnvironmentModel, html_url: str) -> None:
    """Send HTML welcome email to the customer using AWS SES."""
    if not config.ses_sender_email:
        logger.warning("No SES sender email configured — skipping customer welcome email")
        return

    admin_email = env.contact_email or f"admin@{env.target_env_name}.com"
    
    # 1. Fetch admin temporary password from Secrets Manager
    sm = boto3.client("secretsmanager", region_name=config.region)
    secret_name = f"{env.target_env_name}/admin-bootstrap"
    try:
        resp = sm.get_secret_value(SecretId=secret_name)
        payload = json.loads(resp.get("SecretString", "{}"))
        temp_password = payload.get("admin_password", "[Contact Support for Password]")
    except Exception as e:
        logger.error(f"Could not fetch temp password from {secret_name}", exc_info=e)
        temp_password = "[Contact Support for Password]"

    # 2. Build Email Content
    assess_url = env.assess_url or f"http://catalyst-assess-{env.target_env_name}.s3-website.{config.region}.amazonaws.com"
    staff_url = f"https://{env.target_env_name}.{env.amplify_app_id}.amplifyapp.com"
    subject = f"Welcome to Catalyst! Your Environment is Ready"
    
    body_html = f"""
    <html>
    <head></head>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <h2>Welcome to Catalyst, {env.company_name}!</h2>
        <p>Your dedicated multi-tenant environment has been successfully provisioned.</p>
        
        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #117D70; margin: 20px 0;">
            <h3>Access Your Portals</h3>
            <p><strong>Assess Portal (S3):</strong> <a href="{assess_url}">{assess_url}</a></p>
            <p><strong>Staff Portal (Amplify):</strong> <a href="{staff_url}">{staff_url}</a></p>
            <br/>
            <p><strong>Admin Email:</strong> {admin_email}</p>
            <p><strong>Temporary Password:</strong> {temp_password}</p>
        </div>
        
        <p><i>Note: You will be required to change your password upon first login.</i></p>
        
        <hr/>
        <p style="font-size: 12px; color: #666;">This is an automated message. If you have any questions, please contact support.</p>
    </body>
    </html>
    """

    body_text = (
        f"Welcome to Catalyst, {env.company_name}!\n\n"
        f"Your dedicated multi-tenant environment has been successfully provisioned.\n\n"
        f"Access Your Portals\n"
        f"Assess Portal: {assess_url}\n"
        f"Staff Portal: {staff_url}\n"
        f"Admin Email: {admin_email}\n"
        f"Temporary Password: {temp_password}\n\n"
        f"Note: You will be required to change your password upon first login.\n"
    )

    # 3. Send Email via SES
    ses = boto3.client("ses", region_name=config.region)
    try:
        ses.send_email(
            Source=config.ses_sender_email,
            Destination={'ToAddresses': [admin_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': body_html, 'Charset': 'UTF-8'},
                    'Text': {'Data': body_text, 'Charset': 'UTF-8'}
                }
            }
        )
        logger.info("Welcome email sent via SES", extra={"to": admin_email})
    except Exception as e:
        logger.error("Failed to send welcome email via SES", exc_info=e)
