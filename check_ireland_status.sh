#!/usr/bin/env bash
# =============================================================================
#  check_ireland_status.sh — Quick Status Report of Resources in eu-west-1
# =============================================================================
set -euo pipefail
export AWS_PAGER=""

REGION="eu-west-1"

echo "=========================================================="
echo "      CHECKING RESOURCES IN IRELAND ($REGION)            "
echo "=========================================================="

echo "▶ 1. DynamoDB Tables in $REGION:"
TABLES=$(aws dynamodb list-tables --region "$REGION" --query "TableNames" --output text 2>/dev/null || echo "")
if [ -z "$TABLES" ]; then
  echo "  (No tables found yet)"
else
  for tbl in $TABLES; do
    echo "  ✔ $tbl"
  done
  echo "  Total: $(echo "$TABLES" | wc -w) tables"
fi
echo ""

echo "▶ 2. Cognito User Pools in $REGION:"
POOLS=$(aws cognito-idp list-user-pools --region "$REGION" --max-results 20 --query "UserPools[].Name" --output text 2>/dev/null || echo "")
if [ -z "$POOLS" ]; then
  echo "  (No user pools found yet)"
else
  for pool in $POOLS; do
    echo "  ✔ $pool"
  done
fi
echo ""

echo "▶ 3. AppSync GraphQL APIs in $REGION:"
APIS=$(aws appsync list-graphql-apis --region "$REGION" --query "graphqlApis[].name" --output text 2>/dev/null || echo "")
if [ -z "$APIS" ]; then
  echo "  (No AppSync APIs found yet)"
else
  for api in $APIS; do
    echo "  ✔ $api"
  done
fi
echo ""

echo "▶ 4. Core Lambda Functions in $REGION:"
LAMBDAS=$(aws lambda list-functions --region "$REGION" --query "Functions[].FunctionName" --output text 2>/dev/null || echo "")
if [ -z "$LAMBDAS" ]; then
  echo "  (No Lambda functions found yet)"
else
  for fn in $LAMBDAS; do
    echo "  ✔ $fn"
  done
fi
echo ""

echo "▶ 5. Secrets Manager in $REGION:"
SECRETS=$(aws secretsmanager list-secrets --region "$REGION" --query "SecretList[].Name" --output text 2>/dev/null || echo "")
if [ -z "$SECRETS" ]; then
  echo "  (No secrets found yet)"
else
  for sec in $SECRETS; do
    echo "  ✔ $sec"
  done
fi
echo ""

echo "▶ 6. Amplify Apps in $REGION:"
AMPS=$(aws amplify list-apps --region "$REGION" --query "apps[].name" --output text 2>/dev/null || echo "")
if [ -z "$AMPS" ]; then
  echo "  (No Amplify apps found yet)"
else
  for app in $AMPS; do
    echo "  ✔ $app"
  done
fi
echo "=========================================================="
