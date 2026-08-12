import logging
import os
from moto import mock_aws
import boto3
from src.common.models import EnvironmentModel
from src.common.constants import ResourceStatus
from src.provisioners.dynamodb_provisioner import DynamoDBProvisioner
from src.provisioners.secrets_provisioner import SecretsProvisioner

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Simulation")

class DummyStateManager:
    def upsert_resource(self, env_id, record):
        pass

@mock_aws
def simulate():
    os.environ["AWS_DEFAULT_REGION"] = "eu-central-1"
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

    logger.info("Starting safe local dry-run simulation (using Moto mock)...")
    
    # 1. Setup Mock Source Environment
    ddb = boto3.client("dynamodb", region_name="eu-central-1")
    ddb.create_table(
        TableName="Attend-dev",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST"
    )
    
    sm = boto3.client("secretsmanager", region_name="eu-central-1")
    sm.create_secret(Name="dev/app-secret", SecretString="my-fake-secret")
    
    logger.info("Mock source resources created ('dev').")

    # 2. Run Provisioners
    env = EnvironmentModel(
        source_env_name="dev",
        target_env_name="marketplace-demo",
        region="eu-central-1",
        account_id="123456789012"
    )

    state_mgr = DummyStateManager()

    logger.info("\n--- Running DynamoDB Provisioner ---")
    p1 = DynamoDBProvisioner("eu-central-1", "123456789012", state_mgr)
    res1 = p1.provision(env)
    logger.info(f"Result: {res1.target_id} - {res1.status}")

    logger.info("\n--- Running Secrets Provisioner ---")
    p2 = SecretsProvisioner("eu-central-1", "123456789012", state_mgr)
    res2 = p2.provision(env)
    logger.info(f"Result: {res2.target_id} - {res2.status}")

    logger.info("\n--- Verifying Cloned Mock Resources ---")
    tables = ddb.list_tables()["TableNames"]
    logger.info(f"DynamoDB Tables in mock AWS: {tables}")
    
    secrets = sm.list_secrets()["SecretList"]
    logger.info(f"Secrets in mock AWS: {[s['Name'] for s in secrets]}")
    
    logger.info("\nSimulation Complete! No real AWS resources were touched.")

if __name__ == "__main__":
    simulate()
