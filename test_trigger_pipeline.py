#!/usr/bin/env python3
"""
test_trigger_pipeline.py — Triggers a real test execution of the Ireland Step Functions pipeline.
"""
import json
import boto3
from datetime import datetime

REGION = "eu-west-1"
ACCOUNT_ID = "215116348101"
AMPLIFY_APP_ID = "dwblve5k042mx"

sf = boto3.client("stepfunctions", region_name=REGION)

# Find the CloningStateMachine in eu-west-1
machines = sf.list_state_machines().get("stateMachines", [])
cloning_sm = next((m for m in machines if "CloningStateMachine" in m["name"]), None)

if not cloning_sm:
    print("❌ Could not find CloningStateMachine in eu-west-1.")
    exit(1)

sm_arn = cloning_sm["stateMachineArn"]
print(f"✔ Found State Machine: {sm_arn}")

test_env = "ireland-demo-1"

# Use a timestamp suffix so re-runs never clash with ExecutionAlreadyExists
timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
execution_name = f"test-clone-{test_env}-{timestamp}"

input_payload = {
    "environment": {
        "reg_token": "TEST-IRE-001",
        "company_name": "Ireland Demo Company",
        "contact_email": "admin@ireland-demo.com",
        "source_env_name": "dev",
        "target_env_name": test_env,
        "source_region": REGION,
        "target_region": REGION,
        "account_id": ACCOUNT_ID,
        "amplify_app_id": AMPLIFY_APP_ID,
    }
}

print(f"Triggering pipeline execution for tenant '{test_env}'...")
print(f"Execution name: {execution_name}")
response = sf.start_execution(
    stateMachineArn=sm_arn,
    name=execution_name,
    input=json.dumps(input_payload),
)

print(f"\n🚀 Execution started successfully!")
print(f"Execution ARN: {response['executionArn']}")
print("\nNow refresh your AWS Console:")
print(f"1. In Step Functions, search for '{execution_name}' — it should show RUNNING.")
print("2. In Amplify (eu-west-1), you will see branch 'ireland-demo-1' created!")
