#!/bin/bash
# Multi-Account Failover Setup - Account 101 (Automation/Workload Account)
# This script provisions the S3 fallback bucket, CloudFront Function, and CloudFront Distribution.

set -e

# Configuration
REGION="eu-central-1"
S3_BUCKET_NAME="fallback-assess-101"
CF_FUNCTION_NAME="AssessHostHeaderPreserve"
ORIGIN_ID_AMPLIFY="PrimaryAmplifyOrigin"
ORIGIN_ID_S3="SecondaryS3Fallback"
AMPLIFY_DOMAIN="act-20260908-1.d246slprgvqfid.amplifyapp.com"

echo "Creating S3 Fallback Bucket ($S3_BUCKET_NAME) in $REGION..."
aws s3api create-bucket --bucket "$S3_BUCKET_NAME" --region "$REGION" --create-bucket-configuration LocationConstraint="$REGION"

echo "Applying S3 Public Access Block..."
aws s3api put-public-access-block --bucket "$S3_BUCKET_NAME" --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "Creating CloudFront Function ($CF_FUNCTION_NAME)..."
cat > cf_function.js << 'EOF'
function handler(event) {
    var request = event.request;
    var headers = request.headers;
    var host = headers.host ? headers.host.value : '';
    headers['x-forwarded-host'] = { value: host };
    return request;
}
EOF

aws cloudfront create-function \
    --name "$CF_FUNCTION_NAME" \
    --function-config Comment="Injects X-Forwarded-Host for Amplify",Runtime="cloudfront-js-1.0" \
    --function-code fileb://cf_function.js

echo "Publishing CloudFront Function..."
ETAG=$(aws cloudfront describe-function --name "$CF_FUNCTION_NAME" --query 'ETag' --output text)
aws cloudfront publish-function --name "$CF_FUNCTION_NAME" --if-match "$ETAG"

echo "Setup complete! Please configure the CloudFront Distribution manually in the AWS Console linking these resources."
