import json
import os
from typing import Any, Dict

from src.common.logger import get_logger
from src.common.models import EnvironmentModel
from src.common.constants import ProvisionStep
from src.provisioners import (
    DynamoDBProvisioner,
    SeedProvisioner,
    SecretsProvisioner,
    CognitoProvisioner,
    LambdaProvisioner,
    APIGatewayProvisioner,
    AppSyncProvisioner,
    AmplifyProvisioner,
    S3FrontendProvisioner,
)
from src.state.environment_state_manager import EnvironmentStateManager

logger = get_logger(__name__)

# Map Steps to their respective Provisioner classes
PROVISIONER_MAP = {
    ProvisionStep.PROVISION_DYNAMODB: DynamoDBProvisioner,
    ProvisionStep.PROVISION_SEED: SeedProvisioner,
    ProvisionStep.PROVISION_SECRETS: SecretsProvisioner,
    ProvisionStep.PROVISION_COGNITO: CognitoProvisioner,
    ProvisionStep.PROVISION_LAMBDA: LambdaProvisioner,
    ProvisionStep.PROVISION_API_GATEWAY: APIGatewayProvisioner,
    ProvisionStep.PROVISION_APPSYNC: AppSyncProvisioner,
    ProvisionStep.PROVISION_S3_FRONTEND: S3FrontendProvisioner,
    ProvisionStep.PROVISION_AMPLIFY: AmplifyProvisioner,
}

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Unified worker for Step Functions.
    Expects input like:
    {
        "step": "PROVISION_DYNAMODB",
        "environment": { ... EnvironmentModel JSON ... }
    }
    Returns:
    {
        "environment": { ... Updated EnvironmentModel JSON ... }
    }
    """
    logger.info("Pipeline Worker invoked", extra={"step": event.get("step")})
    
    step_name = event.get("step")
    if not step_name:
        raise ValueError("Missing 'step' in event payload")
        
    try:
        step = ProvisionStep(step_name)
    except ValueError:
        raise ValueError(f"Invalid step: {step_name}")

    if step not in PROVISIONER_MAP:
        raise ValueError(f"No provisioner mapped for step: {step}")

    env_data = event.get("environment")
    if not env_data:
        raise ValueError("Missing 'environment' in event payload")

    env = EnvironmentModel(**env_data)
    
    # Initialize Provisioner
    provisioner_class = PROVISIONER_MAP[step]
    state_mgr = EnvironmentStateManager(
        table_name=os.environ.get("STATE_TABLE", "EnvironmentState"),
        region=env.region
    )
    
    provisioner = provisioner_class(
        region=env.region,
        account_id=env.account_id,
        state_manager=state_mgr
    )

    # Execute
    logger.info(f"Executing {provisioner_class.__name__}")
    provisioner.provision(env)
    
    return {
        "environment": env.model_dump(mode="json")
    }
