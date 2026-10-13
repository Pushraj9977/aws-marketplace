import boto3
import argparse
import os

AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

# Default logo — absolute S3 URL so Next.js <Image> and Assess can load it.
# NEVER use a relative filename like "default-logo.png" — it will 404 in production.
DEFAULT_LOGO = "https://alliancecaretech-public-resources.s3.amazonaws.com/Engage/act_banner_Group3.svg"


def seed_dynamodb(env_name, admin_email=None, company_name=None):
    print(f"=== Seeding DynamoDB Tables for Environment: {env_name} ===")
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    dynamodb_client = boto3.client('dynamodb', region_name=AWS_REGION)

    # Tables - Shared DB Architecture
    config_table_name = "Catalyst_CompConfig"
    staff_table_name = "catEncounter_StaffTable"
    thought_table_name = "Thought_Table"

    org_id = f"org-{env_name}"
    if not admin_email:
        admin_email = f"admin@{env_name}.com"
    if not company_name:
        company_name = env_name

    try:
        # Seed Configuration
        print(f"Seeding Organization Config to: {config_table_name}")
        config_table = dynamodb.Table(config_table_name)
        config_table.put_item(
            Item={
                'serialNumber': org_id,
                'organizationId': org_id,
                'organizationName': org_id,
                'environment': env_name,
                'appColor': '#1f733d',
                'assessColor': '#1f733d',
                'staffColor': '#1f733d',
                # Both scan count fields must be present to avoid NaN in the Assess UI
                'appDHAScanCount': '3',
                'assessDHAScanCount': '3',
                'isAppCalories': False,
                'isAppMessages': True,
                'isAssess3d': True,
                'isAssessBiometric': True,
                'isAssessCognitive': True,
                'isAssessLearnBtn': True,
                'isAssessRatina': True,
                'isAssessSelfAssessment': True,
                'isOthers': True,
                # Use absolute S3 URLs — relative filenames like "default-logo.png" 404 in Next.js
                'appLogo': DEFAULT_LOGO,
                'assessLogo': DEFAULT_LOGO,
                # Use absolute S3 URL for staffLogo — relative paths 404 in Next.js <Image>
                'staffLogo': DEFAULT_LOGO,
                # assessPrefix is stored as plain text — backendApi uses it directly.
                # Do NOT encrypt it; crypto.js decryptMessage handles plaintext gracefully.
                'assessPrefix': 'ACTI',
                'appName': 'Engage',
                'assessName': 'Assess',
                'assessHeader': company_name,
                'staffHeader': company_name,
                'lang': 'en',
                'solution': 'Full-Solution',
            }
        )
        print("  -> Configuration seeded successfully.")
    except Exception as e:
        print(f"  -> ❌ Failed to seed Configuration table: {e}")

    try:
        # Seed Admin Staff
        print(f"Seeding Admin Staff to: {staff_table_name}")
        staff_table = dynamodb.Table(staff_table_name)
        staff_table.put_item(
            Item={
                'staffId': 'FTS-000001',
                'organizationId': org_id,
                's_EmailId': admin_email,
                's_FirstName': 'Admin',
                's_LastName': 'User',
                'role': 'eng_acc_gr_7_super_admin',
                's_Theme': 'dark'
            }
        )
        print("  -> Admin Staff seeded successfully.")
    except Exception as e:
        print(f"  -> ❌ Failed to seed Staff table: {e}")

    try:
        # Seed initial Thought of the Day to prevent "data is undefined" runtime error
        print(f"Seeding initial Thought of the Day to: {thought_table_name}")
        # serialNumber is the primary key of Thought_Table
        thought_serial = f"thought-{org_id}"
        dynamodb_client.put_item(
            TableName=thought_table_name,
            Item={
                'serialNumber': {'S': thought_serial},
                'organizationId': {'S': org_id},
                'thoughtOfDay': {'S': 'Welcome to your wellness journey! Start today with a small step toward a healthier life.'},
                'organizationName': {'S': org_id},
            },
            # Only insert if this serialNumber does not exist yet (idempotent)
            ConditionExpression='attribute_not_exists(serialNumber)',
        )
        print("  -> Thought of the Day seeded successfully.")
    except dynamodb_client.exceptions.ConditionalCheckFailedException:
        print("  -> Thought_Table entry already exists, skipping.")
    except Exception as e:
        print(f"  -> ❌ Failed to seed Thought_Table: {e}")

    print("=== Seeding Complete ===\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed initial tenant data into DynamoDB")
    parser.add_argument("--env", type=str, required=True, help="Target Environment Name (e.g., marketplacetest6)")
    parser.add_argument("--email", type=str, default=None, help="Admin email address")
    parser.add_argument("--company", type=str, default=None, help="Company / display name")
    args = parser.parse_args()

    seed_dynamodb(args.env, args.email, args.company)
