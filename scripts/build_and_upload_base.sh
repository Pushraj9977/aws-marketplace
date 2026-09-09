#!/bin/bash
# =============================================================================
# build_and_upload_base.sh
# One-time script: build the Catalyst-HealthyAging-Assess-test frontend
# and upload the compiled bundle to the base assets S3 bucket.
# Run this manually whenever you update the Assess frontend code.
# =============================================================================
set -e

ASSESS_DIR="$(cd "$(dirname "$0")/../../Catalyst-HealthyAging-Assess-test" && pwd)"
BASE_BUCKET="catalyst-assess-base-assets-eu-central-1"
REGION="eu-central-1"

echo "============================================"
echo " Step 1: Building Catalyst-Assess frontend"
echo "============================================"
cd "$ASSESS_DIR"

# Install dependencies if node_modules is missing
if [ ! -d "node_modules" ]; then
    echo "[INFO] Installing dependencies..."
    npm install --legacy-peer-deps
fi

echo "[INFO] Running production build..."
npm run build

echo "[INFO] Build complete. Output: $ASSESS_DIR/build/"
ls -la build/

echo ""
echo "============================================"
echo " Step 2: Creating base assets S3 bucket"
echo "============================================"

# Create bucket (idempotent — no error if it already exists)
if aws s3 ls "s3://$BASE_BUCKET" --region "$REGION" 2>&1 | grep -q 'NoSuchBucket'; then
    aws s3 mb "s3://$BASE_BUCKET" --region "$REGION"
    echo "[INFO] Created bucket: $BASE_BUCKET"
else
    echo "[INFO] Bucket already exists: $BASE_BUCKET"
fi

echo ""
echo "============================================"
echo " Step 3: Uploading build/ to S3"
echo "============================================"
aws s3 sync build/ "s3://$BASE_BUCKET/" \
    --region "$REGION" \
    --delete \
    --cache-control "public,max-age=31536000,immutable" \
    --exclude "*.html" \
    --exclude "config.js"

# Upload index.html separately with no-cache so tenants always get fresh config
aws s3 cp build/index.html "s3://$BASE_BUCKET/index.html" \
    --region "$REGION" \
    --cache-control "no-cache,no-store,must-revalidate" \
    --content-type "text/html"

echo ""
echo "============================================"
echo " Done! Base assets uploaded to:"
echo " s3://$BASE_BUCKET/"
echo "============================================"
