#!/usr/bin/env bash
# =============================================================================
# deploy_to_ireland.sh
# Rebuilds the Lambda deployment package with all dependencies (pydantic, etc.)
# and updates every Lambda function in eu-west-1 (Ireland).
# Run this from Git Bash inside the cloning-platform/ directory.
# Usage:  bash deploy_to_ireland.sh
# =============================================================================

set -e

REGION="eu-west-1"
STACK_NAME="ACTTest-Ireland"   # change if your Ireland stack has a different name

echo "============================================================"
echo " Lambda Rebuild + Deploy to Ireland (eu-west-1)"
echo "============================================================"

# ── 1. Detect the actual stack name if needed ─────────────────────────────────
echo ""
echo "[1/5] Detecting Lambda functions in eu-west-1..."

# List all Lambda function names that belong to the Ireland stack
FUNCTIONS=$(aws lambda list-functions \
  --region "$REGION" \
  --query "Functions[?contains(FunctionName,'ACTTest') || contains(FunctionName,'Ireland') || contains(FunctionName,'Cloning') || contains(FunctionName,'Pipeline') || contains(FunctionName,'Marketplace') || contains(FunctionName,'HealthCheck') || contains(FunctionName,'Report')].FunctionName" \
  --output text 2>/dev/null)

if [ -z "$FUNCTIONS" ]; then
  echo "  Could not auto-detect functions. Trying CloudFormation stack resources..."
  FUNCTIONS=$(aws cloudformation list-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResourceSummaries[?ResourceType=='AWS::Lambda::Function'].PhysicalResourceId" \
    --output text 2>/dev/null || true)
fi

if [ -z "$FUNCTIONS" ]; then
  echo "  ❌ No Lambda functions found. Please verify the stack name in this script."
  echo "     Run: aws cloudformation list-stacks --region eu-west-1"
  exit 1
fi

echo "  Found functions:"
for fn in $FUNCTIONS; do echo "    - $fn"; done

# ── 2. Build the zip with dependencies ───────────────────────────────────────
echo ""
echo "[2/5] Installing dependencies and building deployment zip..."

BUILD_DIR="/tmp/lambda_build_$$"
ZIP_PATH="/tmp/lambda_package_$$.zip"

rm -rf "$BUILD_DIR" "$ZIP_PATH"
mkdir -p "$BUILD_DIR"

# Install requirements into the build directory
echo "  Running: pip install -r requirements.txt --target $BUILD_DIR --quiet"
pip install -r requirements.txt --target "$BUILD_DIR" --quiet

# Copy source code into the build directory
echo "  Copying src/ into build directory..."
cp -r src "$BUILD_DIR/src"

# Also copy any top-level __init__.py if present
[ -f "__init__.py" ] && cp "__init__.py" "$BUILD_DIR/__init__.py"

# Create the zip
echo "  Creating zip package..."
cd "$BUILD_DIR"
zip -r "$ZIP_PATH" . -x "*.pyc" -x "*/__pycache__/*" -x "*.dist-info/*" > /dev/null
cd - > /dev/null

ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
echo "  ✔ Zip created: $ZIP_PATH ($ZIP_SIZE)"

# ── 3. Update each Lambda function ───────────────────────────────────────────
echo ""
echo "[3/5] Updating Lambda functions in $REGION..."

SUCCESS_COUNT=0
FAIL_COUNT=0

for FN_NAME in $FUNCTIONS; do
  echo -n "  Updating: $FN_NAME ... "
  RESULT=$(aws lambda update-function-code \
    --function-name "$FN_NAME" \
    --zip-file "fileb://$ZIP_PATH" \
    --region "$REGION" \
    --query "LastUpdateStatus" \
    --output text 2>&1)
  
  if echo "$RESULT" | grep -qi "successful\|InProgress"; then
    echo "✔ OK ($RESULT)"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    echo "❌ FAILED"
    echo "     Error: $RESULT"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

# ── 4. Wait for updates to propagate ─────────────────────────────────────────
echo ""
echo "[4/5] Waiting 10 seconds for Lambda updates to propagate..."
sleep 10

# ── 5. Quick smoke test - invoke the pipeline worker ─────────────────────────
echo ""
echo "[5/5] Smoke testing PipelineWorkerFunction..."

# Find the exact name of the pipeline worker function
WORKER_FN=$(aws lambda list-functions \
  --region "$REGION" \
  --query "Functions[?contains(FunctionName,'PipelineWorker')].FunctionName | [0]" \
  --output text 2>/dev/null)

if [ -z "$WORKER_FN" ] || [ "$WORKER_FN" = "None" ]; then
  # Try to find it from the list we already got
  WORKER_FN=$(echo "$FUNCTIONS" | tr '\t' '\n' | grep -i "PipelineWorker" | head -1)
fi

if [ -n "$WORKER_FN" ] && [ "$WORKER_FN" != "None" ]; then
  echo "  Invoking: $WORKER_FN"
  INVOKE_RESULT=$(aws lambda invoke \
    --function-name "$WORKER_FN" \
    --region "$REGION" \
    --payload '{"step":"HEALTH","environment":{"target_env_name":"test"}}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/lambda_response_$$.json 2>&1 || true)
  
  if [ -f /tmp/lambda_response_$$.json ]; then
    RESPONSE=$(cat /tmp/lambda_response_$$.json)
    if echo "$RESPONSE" | grep -qi "pydantic\|ImportModuleError\|Runtime"; then
      echo "  ❌ Still seeing import errors:"
      echo "     $RESPONSE"
    else
      echo "  ✔ Function responded (no import errors):"
      echo "     $RESPONSE" | head -c 200
    fi
    rm -f /tmp/lambda_response_$$.json
  fi
else
  echo "  ⚠ Could not find PipelineWorkerFunction to test (skipping smoke test)"
fi

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -rf "$BUILD_DIR" "$ZIP_PATH"

echo ""
echo "============================================================"
echo " Done!"
echo "   ✔ Updated: $SUCCESS_COUNT functions"
[ "$FAIL_COUNT" -gt 0 ] && echo "   ❌ Failed:  $FAIL_COUNT functions"
echo ""
echo " Next step: run your test from the aws-marketplace/ directory:"
echo "   cd .. && python test_trigger_pipeline.py"
echo "============================================================"
