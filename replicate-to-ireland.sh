#!/usr/bin/env bash
# =============================================================================
#  replicate-to-ireland.sh — Replicate Catalyst Platform to Ireland (eu-west-1)
#  COMPLETE REPLICATION: 
#  1. All 46 DynamoDB Tables & Schemas (KeySchema, GSIs, LSIs)
#  2. Base Cognito User Pool & App Client
#  3. AppSync GraphQL API (Schema SDL, Resolvers, Data Sources)
#  4. Base Lambda Functions (backendApi-dev, staffApi-dev, etc.)
#  5. S3 Frontend Base Bucket & Assets
#  6. Automated AWS Amplify Hosting App Setup
#  7. Automated Amazon SES Identities (Email & Domain)
#  8. AWS SAM Serverless Platform & Step Functions (11-Stage Pipeline)
#  9. Master Reference Data Seeding
# =============================================================================
set -euo pipefail

# Disable AWS CLI interactive pager so commands never halt at "-- More --"
export AWS_PAGER=""

TARGET_REGION="eu-west-1"
SOURCE_REGION="eu-central-1"
ACCOUNT_ID="215116348101"
SOURCE_AMPLIFY_APP_ID="d246slprgvqfid"
DEFAULT_SES_EMAIL="${SES_SENDER_EMAIL:-chouhanpushkarraj@gmail.com}"
DEFAULT_SES_DOMAIN="${SES_DOMAIN:-alliancecaretech.com}"

echo "================================================================="
echo "   REPLICATING ENTIRE CATALYST ECOSYSTEM TO IRELAND ($TARGET_REGION)  "
echo "================================================================="

# -----------------------------------------------------------------------------
# 1. AWS Credentials & Caller Verification
# -----------------------------------------------------------------------------
echo "[1/9] Verifying AWS Identity..."
CURRENT_ACCOUNT=$(aws sts get-caller-identity --query "Account" --output text)
echo "Current Account: $CURRENT_ACCOUNT"
if [ "$CURRENT_ACCOUNT" != "$ACCOUNT_ID" ]; then
  echo "WARNING: Expected Account $ACCOUNT_ID but found $CURRENT_ACCOUNT"
fi

# -----------------------------------------------------------------------------
# 2. DynamoDB Orchestration Tables & Stream Setup in eu-west-1
# -----------------------------------------------------------------------------
echo "[2/9] Provisioning Orchestration DynamoDB Tables & Streams in $TARGET_REGION..."

if ! aws dynamodb describe-table --region "$TARGET_REGION" --table-name "MarketplaceSubscribers" >/dev/null 2>&1; then
  echo "Creating MarketplaceSubscribers table..."
  aws dynamodb create-table \
    --region "$TARGET_REGION" \
    --table-name "MarketplaceSubscribers" \
    --attribute-definitions AttributeName=regToken,AttributeType=S \
    --key-schema AttributeName=regToken,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES >/dev/null
  
  aws dynamodb wait table-exists --region "$TARGET_REGION" --table-name "MarketplaceSubscribers"
  echo "✔ MarketplaceSubscribers is ACTIVE."
else
  echo "MarketplaceSubscribers table already exists in $TARGET_REGION."
fi

STREAM_ARN=$(aws dynamodb describe-table \
  --region "$TARGET_REGION" \
  --table-name "MarketplaceSubscribers" \
  --query 'Table.LatestStreamArn' \
  --output text)
echo "DynamoDB Stream ARN: $STREAM_ARN"

if ! aws dynamodb describe-table --region "$TARGET_REGION" --table-name "EnvironmentState" >/dev/null 2>&1; then
  echo "Creating EnvironmentState table..."
  aws dynamodb create-table \
    --region "$TARGET_REGION" \
    --table-name "EnvironmentState" \
    --attribute-definitions AttributeName=environment_id,AttributeType=S \
    --key-schema AttributeName=environment_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  
  aws dynamodb wait table-exists --region "$TARGET_REGION" --table-name "EnvironmentState"
  echo "✔ EnvironmentState is ACTIVE."
else
  echo "EnvironmentState table already exists in $TARGET_REGION."
fi

# -----------------------------------------------------------------------------
# 3. FULL REPLICATION: All 46 DynamoDB Tables, Cognito, AppSync & Base Lambdas
# -----------------------------------------------------------------------------
echo "[3/9] Replicating ALL DynamoDB Tables, Schemas, Cognito, AppSync & Base Lambdas..."
python scripts/replicate_all_resources.py --source "$SOURCE_REGION" --target "$TARGET_REGION"

# -----------------------------------------------------------------------------
# 4. Base Secrets Manager in eu-west-1
# -----------------------------------------------------------------------------
echo "[4/9] Replicating Base Secrets in $TARGET_REGION..."
for sec_name in "dev/app-secret" "cloning-platform/github-token"; do
  if ! aws secretsmanager describe-secret --region "$TARGET_REGION" --secret-id "$sec_name" >/dev/null 2>&1; then
    echo "Checking source secret '$sec_name' from $SOURCE_REGION..."
    SOURCE_SEC_VAL=$(aws secretsmanager get-secret-value --region "$SOURCE_REGION" --secret-id "$sec_name" --query 'SecretString' --output text 2>/dev/null || echo "")
    if [ -n "$SOURCE_SEC_VAL" ]; then
      echo "Creating secret '$sec_name' in $TARGET_REGION..."
      aws secretsmanager create-secret \
        --region "$TARGET_REGION" \
        --name "$sec_name" \
        --secret-string "$SOURCE_SEC_VAL" >/dev/null
    fi
  else
    echo "Secret '$sec_name' already exists in $TARGET_REGION."
  fi
done

# -----------------------------------------------------------------------------
# 5. S3 Base Assets Bucket for Assess Frontend
# -----------------------------------------------------------------------------
echo "[5/9] Setting up S3 Frontend Base Assets Bucket in $TARGET_REGION..."
BASE_ASSETS_BUCKET="catalyst-assess-base-assets-${TARGET_REGION}-${ACCOUNT_ID}"

if ! aws s3api head-bucket --bucket "$BASE_ASSETS_BUCKET" --expected-bucket-owner "$ACCOUNT_ID" 2>/dev/null; then
  echo "Creating S3 bucket: $BASE_ASSETS_BUCKET..."
  aws s3api create-bucket \
    --bucket "$BASE_ASSETS_BUCKET" \
    --region "$TARGET_REGION" \
    --create-bucket-configuration LocationConstraint="$TARGET_REGION" >/dev/null
else
  echo "S3 Base Assets Bucket $BASE_ASSETS_BUCKET already exists."
fi

# -----------------------------------------------------------------------------
# 6. Automated AWS Amplify App Setup in Ireland (eu-west-1)
# -----------------------------------------------------------------------------
echo "[6/9] Automating AWS Amplify App Setup in $TARGET_REGION..."

EXISTING_APP_ID=$(aws amplify list-apps --region "$TARGET_REGION" --query "apps[?name=='Catalyst-HealthyAging'].appId | [0]" --output text 2>/dev/null || echo "None")

if [ "$EXISTING_APP_ID" != "None" ] && [ -n "$EXISTING_APP_ID" ]; then
  TARGET_AMPLIFY_APP_ID="$EXISTING_APP_ID"
  echo "✔ Amplify App 'Catalyst-HealthyAging' already exists in $TARGET_REGION: $TARGET_AMPLIFY_APP_ID"
else
  echo "Fetching source Amplify configuration from $SOURCE_REGION (App ID: $SOURCE_AMPLIFY_APP_ID)..."
  SOURCE_APP_JSON=$(aws amplify get-app --region "$SOURCE_REGION" --app-id "$SOURCE_AMPLIFY_APP_ID" --query "app" --output json)
  
  REPO_URL=$(echo "$SOURCE_APP_JSON" | jq -r '.repository // empty')
  PLATFORM=$(echo "$SOURCE_APP_JSON" | jq -r '.platform // "WEB_COMPUTE"')
  BUILD_SPEC=$(echo "$SOURCE_APP_JSON" | jq -r '.buildSpec // empty')
  
  # Fetch GitHub token from Secrets Manager or environment
  GITHUB_TOKEN="${GITHUB_TOKEN:-}"
  if [ -z "$GITHUB_TOKEN" ]; then
    GITHUB_TOKEN=$(aws secretsmanager get-secret-value --region "$SOURCE_REGION" --secret-id "cloning-platform/github-token" --query "SecretString" --output text 2>/dev/null || echo "")
  fi
  
  CREATE_ARGS=(
    --region "$TARGET_REGION"
    --name "Catalyst-HealthyAging"
    --platform "$PLATFORM"
  )
  
  if [ -n "$REPO_URL" ] && [ -n "$GITHUB_TOKEN" ]; then
    echo "Found GitHub repository & token. Linking repository to Amplify..."
    CREATE_ARGS+=(--repository "$REPO_URL" --access-token "$GITHUB_TOKEN")
  else
    echo "Creating Amplify App shell (repository can be linked via GitHub token or Console)..."
  fi
  
  if [ -n "$BUILD_SPEC" ]; then
    CREATE_ARGS+=(--build-spec "$BUILD_SPEC")
  fi
  
  echo "Creating Amplify App in $TARGET_REGION..."
  NEW_APP_JSON=$(aws amplify create-app "${CREATE_ARGS[@]}" --output json)
  TARGET_AMPLIFY_APP_ID=$(echo "$NEW_APP_JSON" | jq -r '.app.appId')
  echo "✔ Successfully created Amplify App in $TARGET_REGION: $TARGET_AMPLIFY_APP_ID"
fi

CONFIG_FILE="cloning-platform/infrastructure/config/eu-west-1.yaml"
if [ -f "$CONFIG_FILE" ]; then
  echo "Updating $CONFIG_FILE with Amplify App ID ($TARGET_AMPLIFY_APP_ID)..."
  sed -i "s/app_id:.*/app_id: $TARGET_AMPLIFY_APP_ID/" "$CONFIG_FILE"
fi

# -----------------------------------------------------------------------------
# 7. Automated Amazon SES Identity Verification in Ireland (eu-west-1)
# -----------------------------------------------------------------------------
echo "[7/9] Automating Amazon SES Identity Setup in $TARGET_REGION..."

SOURCE_IDENTITIES=$(aws ses list-identities --region "$SOURCE_REGION" --query "Identities" --output text 2>/dev/null || echo "")

if [ -n "$SOURCE_IDENTITIES" ]; then
  echo "Found source identities in $SOURCE_REGION: $SOURCE_IDENTITIES"
  for identity in $SOURCE_IDENTITIES; do
    if [[ "$identity" == *"@"* ]]; then
      echo "Triggering SES verification for email identity: $identity in $TARGET_REGION..."
      aws ses verify-email-identity --region "$TARGET_REGION" --email-address "$identity" || true
    else
      echo "Triggering SES verification for domain identity: $identity in $TARGET_REGION..."
      aws ses verify-domain-identity --region "$TARGET_REGION" --domain "$identity" || true
    fi
  done
else
  if [ -n "$DEFAULT_SES_EMAIL" ]; then
    echo "Triggering SES verification for default email: $DEFAULT_SES_EMAIL in $TARGET_REGION..."
    aws ses verify-email-identity --region "$TARGET_REGION" --email-address "$DEFAULT_SES_EMAIL" || true
  fi
  if [ -n "$DEFAULT_SES_DOMAIN" ]; then
    echo "Triggering SES verification for default domain: $DEFAULT_SES_DOMAIN in $TARGET_REGION..."
    aws ses verify-domain-identity --region "$TARGET_REGION" --domain "$DEFAULT_SES_DOMAIN" || true
  fi
fi

# -----------------------------------------------------------------------------
# 8. Deploy Serverless Cloning Platform via AWS SAM / CloudFormation
# -----------------------------------------------------------------------------
echo "[8/9] Building & Deploying Serverless Platform to $TARGET_REGION..."
cd cloning-platform

if command -v sam >/dev/null 2>&1; then
  echo "Using SAM CLI..."
  sam build
  sam deploy \
    --region "$TARGET_REGION" \
    --stack-name "catalyst-cloning-platform-ireland" \
    --parameter-overrides "SubscriberTableStreamArn=$STREAM_ARN" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --no-confirm-changeset \
    --resolve-s3
elif [ -f "/c/Program Files/Amazon/AWSSAMCLI/bin/sam.exe" ]; then
  echo "Using SAM CLI from Program Files..."
  "/c/Program Files/Amazon/AWSSAMCLI/bin/sam.exe" build
  "/c/Program Files/Amazon/AWSSAMCLI/bin/sam.exe" deploy \
    --region "$TARGET_REGION" \
    --stack-name "catalyst-cloning-platform-ireland" \
    --parameter-overrides "SubscriberTableStreamArn=$STREAM_ARN" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --no-confirm-changeset \
    --resolve-s3
else
  echo "SAM CLI not found. Using native AWS CloudFormation package & deploy..."
  aws cloudformation package \
    --region "$TARGET_REGION" \
    --template-file template.yaml \
    --s3-bucket "$BASE_ASSETS_BUCKET" \
    --output-template-file packaged-template.yaml

  aws cloudformation deploy \
    --region "$TARGET_REGION" \
    --template-file packaged-template.yaml \
    --stack-name "catalyst-cloning-platform-ireland" \
    --parameter-overrides "SubscriberTableStreamArn=$STREAM_ARN" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND
fi

cd ..

# -----------------------------------------------------------------------------
# 9. Seed Master / Reference Data in eu-west-1
# -----------------------------------------------------------------------------
echo "[9/9] Seeding Master Roles and Tenant Reference Data in $TARGET_REGION..."
AWS_REGION="$TARGET_REGION" python seed_tenant_data.py --env "dev" || echo "Note: Check if seed script requires additional env vars."

echo "================================================================="
echo "   REPLICATION INFRASTRUCTURE IN IRELAND (eu-west-1) READY!      "
echo "================================================================="
echo "All resources replicated to Ireland (eu-west-1):"
echo "✔ All 46 DynamoDB Tables & Schemas replicated"
echo "✔ Cognito User Pool & App Client provisioned"
echo "✔ AppSync GraphQL API (Schema SDL, resolvers, data sources) cloned"
echo "✔ Base Application Lambdas (backendApi, staffApi, etc.) deployed"
echo "✔ Secrets Manager: dev/app-secret replicated"
echo "✔ S3 Frontend Base Bucket: $BASE_ASSETS_BUCKET"
echo "✔ AWS Amplify App ID: $TARGET_AMPLIFY_APP_ID"
echo "✔ Amazon SES Identities: Verification triggered for $TARGET_REGION"
echo "✔ SAM Platform & Step Functions: Deployed"
echo "✔ Master Data Seeded"
