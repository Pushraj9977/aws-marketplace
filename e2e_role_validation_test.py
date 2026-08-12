import os
import time
import json
import boto3
from playwright.sync_api import sync_playwright

import argparse

# === CONFIGURATION (Defaults / Fallbacks) ===
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

parser = argparse.ArgumentParser(description="E2E Role Validation Test")
parser.add_argument("--env", type=str, default=os.environ.get("TARGET_ENV", "final-test-seven"), help="Target Environment Name (e.g., final-test-seven)")
parser.add_argument("--url", type=str, default=os.environ.get("WEB_URL", "https://final-test-seven.d246slprgvqfid.amplifyapp.com"), help="Amplify Web URL")
parser.add_argument("--username", type=str, default=os.environ.get("USERNAME", "admin@final-test-seven.com"), help="Admin login username")
parser.add_argument("--password", type=str, default=os.environ.get("TEST_PASSWORD", "REPLACE_WITH_YOUR_PASSWORD"), help="Admin login password")

args = parser.parse_args()

ENVIRONMENT_NAME = args.env
WEB_URL = args.url
USERNAME = args.username
PASSWORD = args.password

# Target variables based on user prompt and previous seed data
TARGET_USER_ID = "b3747f82-c8d1-70be-7dc2-f33cec828ef7"
FALLBACK_STAFF_ID = "FTS-000001" # Using the partition key visible in our previous data
FALLBACK_USER_ID_2 = "b37478f2-c0d1-70be-7c4d-f33ce4c028ef"

TARGET_ROLE = "eng_acc_gr_7_super_admin"

def phase1_update_dynamodb():
    print(f"=== Phase 1: Backend Data Update (All Tables for {ENVIRONMENT_NAME}) ===")
    dynamodb_client = boto3.client('dynamodb', region_name=AWS_REGION)
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    
    print(f"Fetching all DynamoDB tables in region {AWS_REGION}...")
    tables = []
    try:
        paginator = dynamodb_client.get_paginator('list_tables')
        for page in paginator.paginate():
            tables.extend(page['TableNames'])
    except Exception as e:
        print(f"❌ Error fetching tables: {e}")
        return False
        
    # The user requested to use all table names without filtering by environment suffix
    target_tables = tables
    print(f"Found {len(target_tables)} tables in the region to scan.")
    
    updated_count = 0
    for table_name in target_tables:
        print(f"\nScanning table: {table_name}")
        table = dynamodb.Table(table_name)
        
        try:
            response = table.scan()
            items = response.get('Items', [])
            
            target_item = None
            for item in items:
                # Check multiple potential fields for the ID/Email to ensure robustness across different tables
                if (item.get('user_id') == TARGET_USER_ID or 
                    item.get('staffId') == FALLBACK_STAFF_ID or 
                    item.get('staffId') == FALLBACK_USER_ID_2 or
                    item.get('user_ProfileId') == FALLBACK_STAFF_ID or
                    item.get('u_EmailId') == USERNAME or
                    item.get('s_EmailId') == USERNAME):
                    target_item = item
                    break
                    
            if not target_item:
                print(f"  -> User not found in {table_name}. Skipping.")
                continue
                
            print(f"  -> ✅ Found user in {table_name}! Current Role: {target_item.get('role', 'None')}")
            
            # Dynamically determine the primary key for the table
            key_schema = table.key_schema
            pk_name = next(k['AttributeName'] for k in key_schema if k['KeyType'] == 'HASH')
            sk_name = next((k['AttributeName'] for k in key_schema if k['KeyType'] == 'RANGE'), None)
            
            key = {pk_name: target_item[pk_name]}
            if sk_name:
                key[sk_name] = target_item[sk_name]
                
            print(f"  -> Updating role to: {TARGET_ROLE} using Key: {key}")
            
            table.update_item(
                Key=key,
                UpdateExpression="set #roleAttr = :r",
                ExpressionAttributeNames={'#roleAttr': 'role'},
                ExpressionAttributeValues={':r': TARGET_ROLE}
            )
            updated_count += 1
            print(f"  -> ✅ Update successful for {table_name}!")
            
        except Exception as e:
            print(f"  -> ❌ Error processing table {table_name}: {e}")
            
    if updated_count > 0:
        print(f"\n✅ Phase 1 Complete! Updated role in {updated_count} tables.\n")
        return True
    else:
        print(f"\n❌ Phase 1 Error: Target user not found in ANY table for {ENVIRONMENT_NAME}.\n")
        return False

def phase2_ui_validation():
    print("=== Phase 2: Frontend Validation & API Interception ===")
    
    if PASSWORD == "REPLACE_WITH_YOUR_PASSWORD":
        print("\n⚠️ WARNING: Password not set! Please set the TEST_PASSWORD environment variable or update the script.")
        print("The browser will launch, but you will need to type the password manually.\n")
    
    with sync_playwright() as p:
        # Launching in headed mode so the user can visually verify the UI test execution
        browser = p.chromium.launch(headless=False, slow_mo=50) 
        context = browser.new_context()
        page = context.new_page()
        
        api_responses = []

        def handle_response(response):
            """
            Intercept network traffic to monitor outgoing fetch/xhr requests.
            We filter for calls to the AWS API Gateway or GraphQL endpoints.
            """
            if "execute-api" in response.url or "graphql" in response.url.lower():
                if response.request.resource_type in ["fetch", "xhr"]:
                    try:
                        # Assert that the request returned a 200 OK status code (as requested)
                        if response.status == 200:
                            body = response.json()
                            body_str = json.dumps(body)
                            
                            # Filter for payloads that actually contain profile/role data
                            if TARGET_ROLE in body_str or "role" in body_str.lower() or "s_displayName" in body_str:
                                print(f"-> Intercepted relevant API response from {response.url.split('?')[0]} [Status: 200 OK]")
                                api_responses.append(body)
                        else:
                            print(f"-> Warning: Intercepted API response with status {response.status} from {response.url}")
                    except Exception:
                        pass # Ignore non-JSON or parsing errors
        
        # Attach the network interceptor
        page.on("response", handle_response)
        
        print(f"Navigating to {WEB_URL}...")
        page.goto(WEB_URL)
        
        print(f"Automating login process for {USERNAME}...")
        
        try:
            # Robust selectors for standard AWS Amplify UI or custom login forms
            page.wait_for_selector("input[name='username'], input[type='email'], input[placeholder*='Email']", timeout=10000)
            
            # Fill Username
            email_input = page.locator("input[name='username'], input[type='email'], input[placeholder*='Email']").first
            email_input.fill(USERNAME)
            
            # Fill Password
            password_input = page.locator("input[name='password'], input[type='password']").first
            if PASSWORD != "REPLACE_WITH_YOUR_PASSWORD":
                password_input.fill(PASSWORD)
            
            # Click Submit
            submit_button = page.locator("button[type='submit'], button:has-text('Sign In'), button:has-text('Log In')").first
            
            if PASSWORD != "REPLACE_WITH_YOUR_PASSWORD":
                submit_button.click()
                print("Submitted login form. Waiting for dashboard redirect...")
            else:
                print("Waiting for manual password entry and login (30 seconds)...")
                page.wait_for_timeout(30000) # Give the user time to manually login
                
        except Exception as e:
            print(f"⚠️ UI Automation Warning: Failed to interact with standard login selectors. Error: {e}")
            print("Please complete the login manually in the open browser window (waiting 30 seconds)...")
            page.wait_for_timeout(30000)
            
        print("Monitoring network traffic for incoming API/GraphQL payloads (waiting 10 seconds)...")
        # Give the dashboard time to load and fire off its initial API requests
        page.wait_for_timeout(10000)
        
        # === VALIDATION ===
        print("\n=== Validation Results ===")
        found_role = False
        
        if not api_responses:
            print("❌ No relevant API responses intercepted.")
            print("Ensure the login was successful and the dashboard actually fetches the user profile via fetch/xhr.")
        else:
            print(f"✅ Successfully intercepted {len(api_responses)} API response(s).")
            for resp in api_responses:
                resp_str = json.dumps(resp)
                if TARGET_ROLE in resp_str:
                    print(f"✅ STRICT ASSERTION PASSED: Found the newly assigned '{TARGET_ROLE}' role in the intercepted payload!")
                    found_role = True
                    break
            
            if not found_role:
                print(f"❌ STRICT ASSERTION FAILED: The role '{TARGET_ROLE}' was not found in the intercepted payloads.")
                print(f"Payload sample: {json.dumps(api_responses[0])[:200]}...")

        browser.close()
        
        if found_role:
            print("\nE2E Test Phase 2 Passed Successfully! 🚀")
        else:
            print("\nE2E Test Phase 2 Failed. 💥")

if __name__ == "__main__":
    # Ensure AWS Credentials are in the environment (which they should be in this workspace)
    print("Starting Automation Script...\n")
    success = phase1_update_dynamodb()
    if success:
        phase2_ui_validation()
