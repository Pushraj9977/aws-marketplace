#!/usr/bin/env bash
# =============================================================================
# install_sam_and_deploy_ireland.sh
#
# PURPOSE : Install AWS SAM CLI (if missing), then build & deploy the
#           cloning-platform stack to eu-west-1 (Ireland) EXACTLY the same
#           way it was deployed to eu-central-1 (Frankfurt).
#
# RUN FROM: Git Bash, inside the cloning-platform/ directory
#   cd "c:/Users/ganesh.sagar/Desktop/3. ACT/aws-marketplace/cloning-platform"
#   bash install_sam_and_deploy_ireland.sh
# =============================================================================

set -euo pipefail
export AWS_PAGER=""

TARGET_REGION="eu-west-1"
ACCOUNT_ID="215116348101"
STACK_NAME="ACTTest-Ireland"          # mirrors "ACTTest" in Frankfurt
S3_PREFIX="ACTTest-Ireland"

SEPARATOR="============================================================"

echo "$SEPARATOR"
echo "  SAM Install + Ireland Deploy"
echo "  Target: $TARGET_REGION | Stack: $STACK_NAME"
echo "$SEPARATOR"

# =============================================================================
# STEP 1 — Install SAM CLI (Windows Git Bash)
# =============================================================================
echo ""
echo "[STEP 1/5] Checking for SAM CLI..."

SAM_CMD=""

# Check standard locations
for candidate in \
  "sam" \
  "/c/Program Files/Amazon/AWSSAMCLI/bin/sam.cmd" \
  "/c/Program Files/Amazon/AWSSAMCLI/bin/sam" \
  "$HOME/.local/bin/sam"
do
  if command -v "$candidate" &>/dev/null 2>&1 || [ -f "$candidate" ]; then
    SAM_CMD="$candidate"
    break
  fi
done

if [ -n "$SAM_CMD" ]; then
  echo "  ✔ SAM CLI already installed: $($SAM_CMD --version)"
else
  echo "  SAM CLI not found. Installing now..."
  echo ""
  echo "  Downloading SAM CLI installer for Windows..."

  # Download the official MSI installer
  SAM_INSTALLER="/tmp/sam-installer.msi"
  curl -L -o "$SAM_INSTALLER" \
    "https://github.com/aws/aws-sam-cli/releases/latest/download/AWS_SAM_CLI_64_PY3.msi" \
    --progress-bar

  echo ""
  echo "  Running MSI installer (this will open a UAC prompt)..."
  msiexec.exe //i "$(cygpath -w "$SAM_INSTALLER")" //quiet //norestart

  echo "  Waiting for install to complete..."
  sleep 10

  # Refresh PATH to pick up newly installed sam
  export PATH="$PATH:/c/Program Files/Amazon/AWSSAMCLI/bin"

  # Verify
  if command -v sam &>/dev/null; then
    SAM_CMD="sam"
    echo "  ✔ SAM CLI installed successfully: $(sam --version)"
  elif [ -f "/c/Program Files/Amazon/AWSSAMCLI/bin/sam.cmd" ]; then
    SAM_CMD="/c/Program Files/Amazon/AWSSAMCLI/bin/sam.cmd"
    echo "  ✔ SAM CLI installed: $($SAM_CMD --version)"
  else
    echo ""
    echo "  ❌ SAM install completed but 'sam' command still not found."
    echo "     Please CLOSE Git Bash, reopen it, and run this script again."
    echo "     Or install manually: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"
    exit 1
  fi
fi

echo ""
echo "  Using SAM: $SAM_CMD"
echo "  Version  : $($SAM_CMD --version)"

# =============================================================================
# STEP 2 — Ensure MarketplaceSubscribers DynamoDB table & Stream exist in Ireland
# =============================================================================
echo ""
echo "[STEP 2/5] Ensuring MarketplaceSubscribers table & stream in $TARGET_REGION..."

if ! aws dynamodb describe-table \
      --region "$TARGET_REGION" \
      --table-name "MarketplaceSubscribers" &>/dev/null; then
  echo "  Table not found. Creating MarketplaceSubscribers in $TARGET_REGION..."
  aws dynamodb create-table \
    --region "$TARGET_REGION" \
    --table-name "MarketplaceSubscribers" \
    --attribute-definitions AttributeName=regToken,AttributeType=S \
    --key-schema AttributeName=regToken,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES \
    --output text --query "TableDescription.TableName" > /dev/null

  echo "  Waiting for table to become ACTIVE..."
  aws dynamodb wait table-exists \
    --region "$TARGET_REGION" \
    --table-name "MarketplaceSubscribers"
  echo "  ✔ MarketplaceSubscribers created."
else
  echo "  ✔ MarketplaceSubscribers already exists."
fi

# Make sure stream is enabled
STREAM_STATUS=$(aws dynamodb describe-table \
  --region "$TARGET_REGION" \
  --table-name "MarketplaceSubscribers" \
  --query "Table.StreamSpecification.StreamEnabled" \
  --output text 2>/dev/null || echo "False")

if [ "$STREAM_STATUS" != "True" ] && [ "$STREAM_STATUS" != "TRUE" ]; then
  echo "  Enabling DynamoDB Stream on MarketplaceSubscribers..."
  aws dynamodb update-table \
    --region "$TARGET_REGION" \
    --table-name "MarketplaceSubscribers" \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES > /dev/null
  echo "  ✔ Stream enabled."
fi

STREAM_ARN=$(aws dynamodb describe-table \
  --region "$TARGET_REGION" \
  --table-name "MarketplaceSubscribers" \
  --query "Table.LatestStreamArn" \
  --output text)

echo "  Stream ARN: $STREAM_ARN"

# =============================================================================
# STEP 3 — Ensure S3 deployment bucket exists in Ireland
# =============================================================================
echo ""
echo "[STEP 3/5] Ensuring S3 deployment bucket exists in $TARGET_REGION..."

DEPLOY_BUCKET="aws-sam-cli-managed-default-samclisourcebucket-ireland-${ACCOUNT_ID}"
# SAM will auto-create its own bucket when --resolve-s3 is used,
# but we verify the base-assets bucket exists too.
BASE_ASSETS_BUCKET="catalyst-assess-base-assets-${TARGET_REGION}-${ACCOUNT_ID}"

for bucket in "$BASE_ASSETS_BUCKET"; do
  if ! aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    echo "  Creating bucket: $bucket..."
    aws s3api create-bucket \
      --bucket "$bucket" \
      --region "$TARGET_REGION" \
      --create-bucket-configuration LocationConstraint="$TARGET_REGION" > /dev/null
    echo "  ✔ Bucket created: $bucket"
  else
    echo "  ✔ Bucket exists: $bucket"
  fi
done

# =============================================================================
# STEP 4 — sam build (installs pydantic + all dependencies into the zip)
# =============================================================================
echo ""
echo "[STEP 4/5] Running 'sam build'..."
echo "  This installs pydantic, pyyaml, jinja2 from requirements.txt"
echo "  into .aws-sam/build/ so they are bundled inside the Lambda zip."
echo ""

# Clean stale build cache first
rm -rf .aws-sam/build

$SAM_CMD build \
  --region "$TARGET_REGION" \
  --template-file template.yaml

echo ""
echo "  ✔ Build complete. Verifying pydantic is in the build..."
if [ -d ".aws-sam/build/PipelineWorkerFunction/pydantic" ]; then
  echo "  ✔ pydantic is present in the build package."
else
  echo "  ⚠ pydantic directory not found in build — check requirements.txt"
fi

# =============================================================================
# STEP 5 — sam deploy to Ireland (identical to Frankfurt)
# =============================================================================
echo ""
echo "[STEP 5/5] Deploying to $TARGET_REGION (stack: $STACK_NAME)..."
echo ""

$SAM_CMD deploy \
  --region "$TARGET_REGION" \
  --stack-name "$STACK_NAME" \
  --s3-prefix "$S3_PREFIX" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "SubscriberTableStreamArn=$STREAM_ARN"

echo ""
echo "$SEPARATOR"
echo "  ✔ DEPLOYMENT COMPLETE"
echo "$SEPARATOR"
echo ""
echo "  Region  : $TARGET_REGION"
echo "  Stack   : $STACK_NAME"
echo "  Stream  : $STREAM_ARN"
echo ""
echo "  Stack outputs:"
aws cloudformation describe-stacks \
  --region "$TARGET_REGION" \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
  --output table 2>/dev/null || echo "  (Run the above manually to see outputs)"

echo ""
echo "  Next step — run your pipeline test:"
echo "    cd .. && python test_trigger_pipeline.py"
echo ""
echo "$SEPARATOR"
