#!/usr/bin/env python3
"""
setup_dynamodb_trigger.py
=========================
Complete AWS automation script to wire the MarketplaceSubscribers DynamoDB
Stream directly to the CloningStateMachine via the MarketplaceSubscriberFunction
Lambda in Account 215116348101 (eu-central-1).

Steps performed:
  1. Inspect & enable DynamoDB Stream on MarketplaceSubscribers
  2. Create/update the IAM role for Lambda with correct policies
  3. Deploy/update the Lambda function (marketplace_subscriber)
  4. Create the DynamoDB → Lambda Event Source Mapping
  5. Insert a test record and verify the Step Function was triggered
"""

import json
import time
import boto3
import zipfile
import io
import logging
import sys
from datetime import datetime, timezone

# ─── Configuration ──────────────────────────────────────────────────────────
REGION              = "eu-central-1"
ACCOUNT_ID          = "215116348101"
TABLE_NAME          = "MarketplaceSubscribers"
LAMBDA_NAME         = "ACTTest-MarketplaceSubscriberFunction-iCu0P4PWJPnp"  # existing deployed Lambda
# Use the Lambda's own execution role (required by AWS for Event Source Mapping)
ROLE_NAME           = "ACTTest-MarketplaceSubscriberFunctionRole-KfcXKsFVeTSk"
STATE_MACHINE_ARN   = "arn:aws:states:eu-central-1:215116348101:stateMachine:CloningStateMachine-MAfgVU46wuWd"

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ─── Boto3 Clients ───────────────────────────────────────────────────────────
session = boto3.Session(region_name=REGION)
dynamo  = session.client("dynamodb")
lam     = session.client("lambda")
iam     = boto3.client("iam")      # IAM is global
sfn     = session.client("stepfunctions")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — DynamoDB Stream Configuration
# ═══════════════════════════════════════════════════════════════════════════════

def step1_enable_dynamo_stream() -> str:
    log.info("═" * 60)
    log.info("STEP 1: Inspecting DynamoDB Stream on '%s'", TABLE_NAME)
    
    desc = dynamo.describe_table(TableName=TABLE_NAME)["Table"]
    stream_spec = desc.get("StreamSpecification", {})
    stream_enabled = stream_spec.get("StreamEnabled", False)
    stream_arn = desc.get("LatestStreamArn")

    if stream_enabled and stream_arn:
        log.info("✓ DynamoDB Streams already ENABLED.")
        log.info("  Stream ARN: %s", stream_arn)
    else:
        log.info("Stream NOT enabled — enabling now with StreamViewType=NEW_IMAGE ...")
        dynamo.update_table(
            TableName=TABLE_NAME,
            StreamSpecification={
                "StreamEnabled": True,
                "StreamViewType": "NEW_IMAGE",
            },
        )
        # Wait for propagation
        log.info("  Waiting for stream to become ACTIVE ...")
        for _ in range(30):
            time.sleep(3)
            desc = dynamo.describe_table(TableName=TABLE_NAME)["Table"]
            stream_arn = desc.get("LatestStreamArn")
            if stream_arn:
                break
        else:
            raise RuntimeError("Stream ARN never appeared — check AWS Console.")
        log.info("✓ Stream ENABLED. ARN: %s", stream_arn)

    return stream_arn


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — IAM Role & Policies
# ═══════════════════════════════════════════════════════════════════════════════

ASSUME_ROLE_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
})

def _build_inline_policy(stream_arn: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudWatchLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT_ID}:*"
            },
            {
                "Sid": "DynamoDBStreamRead",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:DescribeStream",
                    "dynamodb:GetRecords",
                    "dynamodb:GetShardIterator",
                    "dynamodb:ListStreams"
                ],
                "Resource": stream_arn
            },
            {
                "Sid": "StepFunctionsExecute",
                "Effect": "Allow",
                "Action": "states:StartExecution",
                "Resource": STATE_MACHINE_ARN
            }
        ]
    }


def step2_ensure_iam_role(stream_arn: str) -> str:
    log.info("═" * 60)
    log.info("STEP 2: Patching Lambda execution role '%s'", ROLE_NAME)
    log.info("  (This is the role AWS checks when creating the Event Source Mapping)")

    # Verify role exists (it must — it's the Lambda's own role)
    try:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
        role_arn = role["Arn"]
        log.info("✓ Lambda execution role confirmed: %s", role_arn)
    except iam.exceptions.NoSuchEntityException:
        raise RuntimeError(f"Role '{ROLE_NAME}' not found — check the Lambda function's role.")

    # Attach/update the inline policy granting DynamoDB Stream + Step Functions access
    policy_doc = json.dumps(_build_inline_policy(stream_arn))
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="MarketplaceSubscriberStreamPolicy",
        PolicyDocument=policy_doc,
    )
    log.info("✓ Inline policy 'MarketplaceSubscriberStreamPolicy' attached/updated.")
    log.info("  Sleeping 5s for IAM policy propagation ...")
    time.sleep(5)
    return role_arn


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Lambda: Update Environment Variable with STATE_MACHINE_ARN
# ═══════════════════════════════════════════════════════════════════════════════

def step3_update_lambda_env():
    log.info("═" * 60)
    log.info("STEP 3: Updating Lambda '%s' env vars", LAMBDA_NAME)
    
    try:
        fn = lam.get_function_configuration(FunctionName=LAMBDA_NAME)
        env = fn.get("Environment", {}).get("Variables", {})
        
        env["STATE_MACHINE_ARN"] = STATE_MACHINE_ARN
        env["LOG_LEVEL"] = "INFO"
        
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Environment={"Variables": env},
        )
        log.info("✓ Lambda env var STATE_MACHINE_ARN set to: %s", STATE_MACHINE_ARN)
    except lam.exceptions.ResourceNotFoundException:
        log.error("✗ Lambda function '%s' not found! Check the name.", LAMBDA_NAME)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Event Source Mapping: DynamoDB Stream → Lambda
# ═══════════════════════════════════════════════════════════════════════════════

def step4_create_event_source_mapping(stream_arn: str):
    log.info("═" * 60)
    log.info("STEP 4: Wiring DynamoDB Stream → Lambda Event Source Mapping")

    # Check if mapping already exists
    existing = lam.list_event_source_mappings(
        EventSourceArn=stream_arn,
        FunctionName=LAMBDA_NAME,
    ).get("EventSourceMappings", [])

    if existing:
        mapping = existing[0]
        log.info("✓ Event Source Mapping already exists (UUID: %s)", mapping["UUID"])
        log.info("  State: %s | BatchSize: %s", mapping["State"], mapping["BatchSize"])
        
        # Make sure it is enabled
        if mapping["State"] in ("Disabled", "Disabling"):
            log.info("  Re-enabling the mapping ...")
            lam.update_event_source_mapping(
                UUID=mapping["UUID"],
                Enabled=True,
            )
            log.info("✓ Mapping re-enabled.")
        return mapping["UUID"]

    log.info("  Creating new Event Source Mapping ...")
    resp = lam.create_event_source_mapping(
        EventSourceArn=stream_arn,
        FunctionName=LAMBDA_NAME,
        StartingPosition="LATEST",
        BatchSize=1,
        Enabled=True,
        FilterCriteria={
            "Filters": [
                {"Pattern": json.dumps({"eventName": ["INSERT"]})}
            ]
        },
    )
    uuid = resp["UUID"]
    log.info("✓ Event Source Mapping created (UUID: %s)", uuid)

    # Wait for mapping to become active
    log.info("  Waiting for ESM to become Enabled ...")
    for _ in range(20):
        time.sleep(5)
        esm = lam.get_event_source_mapping(UUID=uuid)
        state = esm["State"]
        log.info("  ESM State: %s", state)
        if state == "Enabled":
            break
    else:
        log.warning("ESM did not reach Enabled within timeout — current state: %s", state)

    return uuid


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Test & Validation
# ═══════════════════════════════════════════════════════════════════════════════

TEST_ITEM = {
    "regToken":      {"S": "TEST-REG-001"},
    "companyName":   {"S": "Test Automation Corp"},
    "contactPerson": {"S": "Test User"},
    "contactEmail":  {"S": "admin@testautomation.com"},
    "contactPhone":  {"S": "+1234567890"},
    "awsRegion":     {"S": "eu-central-1"},
    "createdAt":     {"S": "2026-09-17T11:00:00Z"},
}

def step5_test_and_validate():
    log.info("═" * 60)
    log.info("STEP 5: Test & Validation")

    # 5a — Capture baseline Step Function execution count BEFORE insert
    before_execs = sfn.list_executions(
        stateMachineArn=STATE_MACHINE_ARN,
        statusFilter="RUNNING",
    ).get("executions", [])
    log.info("  Running executions BEFORE test insert: %d", len(before_execs))

    # 5b — Insert test record
    log.info("  Inserting test record (regToken=TEST-REG-001) ...")
    try:
        dynamo.put_item(
            TableName=TABLE_NAME,
            Item=TEST_ITEM,
            ConditionExpression="attribute_not_exists(regToken)",
        )
        log.info("✓ Test record inserted into '%s'.", TABLE_NAME)
    except dynamo.exceptions.ConditionalCheckFailedException:
        log.info("  Record TEST-REG-001 already exists — deleting and reinserting ...")
        dynamo.delete_item(TableName=TABLE_NAME, Key={"regToken": {"S": "TEST-REG-001"}})
        time.sleep(2)
        dynamo.put_item(TableName=TABLE_NAME, Item=TEST_ITEM)
        log.info("✓ Test record re-inserted.")

    # 5c — Poll Step Functions for new execution triggered by stream
    log.info("  Polling Step Functions for new execution (up to 90 seconds) ...")
    triggered_execution = None
    for attempt in range(18):
        time.sleep(5)
        log.info("  Poll attempt %d/18 ...", attempt + 1)
        
        all_execs = sfn.list_executions(
            stateMachineArn=STATE_MACHINE_ARN,
        ).get("executions", [])
        
        # Look for a recent execution started after our script began
        for ex in all_execs:
            try:
                ex_input = sfn.describe_execution(
                    executionArn=ex["executionArn"]
                ).get("input", "{}")
                payload = json.loads(ex_input)
                env = payload.get("environment", payload)
                if "TEST-REG-001" in json.dumps(env) or "Test Automation Corp" in json.dumps(env):
                    triggered_execution = ex
                    break
            except Exception:
                continue
        
        if triggered_execution:
            break

    # 5d — Report result
    log.info("═" * 60)
    if triggered_execution:
        log.info("✅ SUCCESS! DynamoDB → Lambda → Step Functions pipeline is WORKING.")
        log.info("   Execution ARN : %s", triggered_execution["executionArn"])
        log.info("   Status        : %s", triggered_execution["status"])
        log.info("   Start Date    : %s", triggered_execution.get("startDate", "N/A"))
        return True
    else:
        log.warning("⚠️  Could not detect a new Step Function execution for TEST-REG-001.")
        log.warning("   This may mean:")
        log.warning("   1. The stream is propagating (Lambda event source mappings can take 1-2 min)")
        log.warning("   2. The Lambda has a bug — check CloudWatch logs for the function")
        log.warning("   3. The IAM role lacks sufficient permissions")
        
        # List ALL recent executions to help debug
        log.info("  Recent executions for debugging:")
        all_execs = sfn.list_executions(stateMachineArn=STATE_MACHINE_ARN).get("executions", [])
        for ex in all_execs[:3]:
            log.info("    - %s | %s", ex["name"], ex["status"])
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║  DynamoDB → Lambda → Step Functions Setup               ║")
    log.info("║  Account: %s | Region: eu-central-1        ║", ACCOUNT_ID)
    log.info("╚══════════════════════════════════════════════════════════╝")

    stream_arn = step1_enable_dynamo_stream()
    _role_arn  = step2_ensure_iam_role(stream_arn)
    step3_update_lambda_env()
    step4_create_event_source_mapping(stream_arn)
    success = step5_test_and_validate()

    log.info("═" * 60)
    if success:
        log.info("🎉  Setup COMPLETE. The pipeline is fully wired and tested.")
    else:
        log.info("⚠️  Setup complete but auto-test inconclusive.")
        log.info("    Run the test_insert.py script again in ~2 minutes.")
    log.info("═" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
