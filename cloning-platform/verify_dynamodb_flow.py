import os
import json
import sys
from unittest.mock import patch, MagicMock

# Set required env vars
os.environ["STATE_MACHINE_ARN"] = "arn:aws:states:eu-central-1:123456789012:stateMachine:Mock"
os.environ["LOG_LEVEL"] = "DEBUG"

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.handlers import marketplace_subscriber

# Mock DynamoDB stream event
mock_event = {
    "Records": [
        {
            "eventID": "1",
            "eventName": "INSERT",
            "dynamodb": {
                "NewImage": {
                    "regToken": {"S": "AMZ-999-DYNAMO"},
                    "companyName": {"S": "DataFlow Test Corp"},
                    "contactEmail": {"S": "dataflow@test.com"},
                    "contactPhone": {"S": "+1234567890"}
                }
            }
        }
    ]
}

print("=== Simulating DynamoDB Stream Event ===")
print(json.dumps(mock_event, indent=2))

@patch("src.handlers.marketplace_subscriber.boto3.client")
@patch("src.state.environment_state_manager.EnvironmentStateManager.create")
def test_handler(mock_create, mock_boto3_client):
    # Setup mock Step Function client
    mock_sf = MagicMock()
    mock_sf.start_execution.return_value = {"executionArn": "arn:aws:states:mock:execution"}
    mock_boto3_client.return_value = mock_sf
    mock_create.return_value = None
    
    # Run the handler
    print("\n=== Executing Lambda Handler ===")
    response = marketplace_subscriber.handler(mock_event, None)
    
    print("\n=== Lambda Response ===")
    print(json.dumps(response, indent=2))
    
    # Verify Step Function was called
    print("\n=== Verification ===")
    if mock_sf.start_execution.called:
        args, kwargs = mock_sf.start_execution.call_args
        print("SUCCESS! Step Function was triggered with payload:")
        print(json.dumps(json.loads(kwargs["input"]), indent=2))
    else:
        print("FAILED! Step Function was not triggered.")

if __name__ == "__main__":
    test_handler()
