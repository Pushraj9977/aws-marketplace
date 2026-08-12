import boto3
import argparse
import os

AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

def seed_dynamodb(env_name):
    print(f"=== Seeding DynamoDB Tables for Environment: {env_name} ===")
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    
    # Tables
    config_table_name = f"catEncounter_ConfigurationTable-{env_name}"
    staff_table_name = f"catEncounter_StaffTable-{env_name}"
    
    org_id = f"org-{env_name}"
    admin_email = f"admin@{env_name}.com"
    
    try:
        # Seed Configuration
        print(f"Seeding Organization Config to: {config_table_name}")
        config_table = dynamodb.Table(config_table_name)
        config_table.put_item(
            Item={
                'organizationId': org_id,
                'isAppCalories': False,
                'isAppMessages': True,
                'appColor': '#1f733d',
                'assessDHAScanCount': '3',
                'appDHAScanCount': '3',
                'environment': env_name,
                'logoName': 'default-logo.png',
                'isAssess3d': True
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
        
    print("=== Seeding Complete ===\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed initial tenant data into DynamoDB")
    parser.add_argument("--env", type=str, required=True, help="Target Environment Name (e.g., final-test-seven)")
    args = parser.parse_args()
    
    seed_dynamodb(args.env)
