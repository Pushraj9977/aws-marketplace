#!/usr/bin/env bash
# =============================================================================
#  marketplace-clone.sh — AWS Marketplace Soft Launch Dynamic Cloner
#
#  Usage:
#    ./marketplace-clone.sh
#    ./marketplace-clone.sh --dry-run
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
log()     { printf "${GREEN}[%s]${RESET} %s\n"         "$(date '+%H:%M:%S')" "$*"; }
info()    { printf "  ${BLUE}➜${RESET}  %s\n"          "$*"; }
warn()    { printf "  ${YELLOW}⚠  %s${RESET}\n"        "$*" >&2; }
die()     { printf "\n  ${RED}✖  ERROR: %s${RESET}\n\n" "$*" >&2; exit 1; }
ok()      { printf "  ${GREEN}✔${RESET}  %s\n"         "$*"; }
section() {
  printf "\n${BOLD}${CYAN}  ▶  %s${RESET}\n" "$1"
  printf "  %s\n" "$(printf '%.0s─' {1..58})"
}
ask() {
  local prompt="$1" default="${2:-}" ans
  [[ -n "$default" ]] \
    && printf "  ${BOLD}?${RESET} %s ${DIM}[%s]${RESET}: " "$prompt" "$default" \
    || printf "  ${BOLD}?${RESET} %s: " "$prompt"
  if [ -e /dev/tty ]; then
    read -r ans < /dev/tty
  else
    ans=""  # non-interactive: use default
  fi
  REPLY="${ans:-$default}"
}
confirm() {
  local prompt="$1" default="${2:-y}" hint ans
  [[ "$default" == "y" ]] && hint="Y/n" || hint="y/N"
  printf "  ${BOLD}?${RESET} %s ${DIM}[%s]${RESET}: " "$prompt" "$hint"
  read -r ans < /dev/tty; ans="${ans:-$default}"; [[ "$ans" =~ ^[Yy]$ ]]
}
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Required: $1 not found. Install it first."; }

# ── Safe Mode ───────────────────────────────────────────────────────────────────
# Deletion and rollback logic has been completely removed as requested.
# If the script fails, resources that were created successfully will remain in AWS.


DRY_RUN=false
TARGET_ENV_ARG=""
SOURCE_ENV_ARG=""
AMPLIFY_APP_ID_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-d)       DRY_RUN=true; shift ;;
    --target-env)       TARGET_ENV_ARG="$2"; shift 2 ;;
    --source-env)       SOURCE_ENV_ARG="$2"; shift 2 ;;
    --amplify-app-id)   AMPLIFY_APP_ID_ARG="$2"; shift 2 ;;
    --help|-h) printf "\nUsage: %s [--dry-run] [--target-env NAME] [--source-env NAME] [--amplify-app-id ID]\n\n" "$0"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

dryrun() { [[ "$DRY_RUN" == "true" ]] && { info "[DRY-RUN] $*"; return 0; } || return 1; }

clear 2>/dev/null || true
printf "${CYAN}${BOLD}"
printf "  ╔══════════════════════════════════════════════════════════╗\n"
printf "  ║      AWS Marketplace Soft Launch — Environment Cloner    ║\n"
printf "  ╚══════════════════════════════════════════════════════════╝\n"
printf "${RESET}\n"
[[ "$DRY_RUN" == "true" ]] && printf "  ${YELLOW}${BOLD}  DRY-RUN — no real AWS resources will be created${RESET}\n\n"

for cmd in aws jq; do require_cmd "$cmd" && ok "$cmd"; done
if [[ "$DRY_RUN" == "false" ]]; then
  CALLER="$(aws sts get-caller-identity)" || die "AWS credentials not configured."
  ACCOUNT_ID="$(jq -r '.Account' <<< "$CALLER")"
  [[ "$ACCOUNT_ID" == "215116348101" ]] || warn "You are not in account 215116348101 (current: $ACCOUNT_ID)"
else
  ACCOUNT_ID="215116348101"
fi

REGION="eu-central-1"

# =============================================================================
#  Fetch Subscribers
# =============================================================================
section "Marketplace Subscribers"
log "Scanning MarketplaceSubscribers table in $REGION..."

SUBSCRIBERS_JSON="$(aws dynamodb scan \
  --region "$REGION" \
  --table-name "MarketplaceSubscribers" \
  --filter-expression "isDeployed = :v1" \
  --expression-attribute-values '{":v1":{"S":"false"}}' 2>/dev/null || aws dynamodb scan \
  --region "$REGION" \
  --table-name "MarketplaceSubscribers" \
  --filter-expression "isDeployed = :v1" \
  --expression-attribute-values '{":v1":{"BOOL":false}}')"

COUNT="$(jq -r '.Count' <<< "$SUBSCRIBERS_JSON")"
if [[ "$COUNT" == "0" ]]; then
  info "No subscribers found with isDeployed = false."
  if [[ -n "$TARGET_ENV_ARG" ]]; then
    TARGET_ENV="$TARGET_ENV_ARG"
    ok "Using --target-env: $TARGET_ENV"
  else
    ask "Target Environment Name manually (since no subscribers were found)" "marketplace-demo"
    TARGET_ENV="$REPLY"
  fi
  REG_TOKEN="manual-token"
else
  printf "  ${BOLD}?${RESET} Select a subscriber to deploy:\n"
  mapfile -t TOKENS < <(jq -r '.Items[].regToken.S // .Items[].regToken.S' <<< "$SUBSCRIBERS_JSON")
  mapfile -t COMPANIES < <(jq -r '.Items[].companyName.S // .Items[].companyName.S' <<< "$SUBSCRIBERS_JSON")
  
  for i in "${!TOKENS[@]}"; do
    printf "    ${CYAN}$((i+1)))${RESET}  ${COMPANIES[$i]}  [Token: ${TOKENS[$i]}]\n"
  done
  
  ask "Select (1-$COUNT)" "1"
  IDX=$((REPLY - 1))
  [[ $IDX -ge 0 && $IDX -lt $COUNT ]] || IDX=0
  
  REG_TOKEN="${TOKENS[$IDX]}"
  COMPANY_NAME="${COMPANIES[$IDX]}"
  
  # Sanitize company name for AWS resource naming
  TARGET_ENV="$(echo "$COMPANY_NAME" | tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9]/-/g')"
  
  ok "Selected subscriber: $COMPANY_NAME ($REG_TOKEN) -> Target Env: $TARGET_ENV"
fi

# =============================================================================
#  Base Environment & Configuration
# =============================================================================
section "Base Environment & Configuration"
if [[ -n "$SOURCE_ENV_ARG" ]]; then
  SOURCE_ENV="$SOURCE_ENV_ARG"
  ok "Using --source-env: $SOURCE_ENV"
else
  ask "Source/Base Environment Name (to clone from)" "demo"
  SOURCE_ENV="$REPLY"
fi

if [[ -n "$AMPLIFY_APP_ID_ARG" ]]; then
  AMPLIFY_APP_ID="$AMPLIFY_APP_ID_ARG"
  ok "Using --amplify-app-id: $AMPLIFY_APP_ID"
else
  ask "Amplify App ID (for frontend deployment)" "d246slprgvqfid"
  AMPLIFY_APP_ID="$REPLY"
fi

# =============================================================================
#  Clone DynamoDB Tables
# =============================================================================
section "DynamoDB Tables (Shared)"
if dryrun "Skipping DynamoDB table creation (using shared database model)"; then :
else
  log "Using single shared DynamoDB database for all environments (per architecture)."
fi

# =============================================================================
#  Clone Secrets Manager
# =============================================================================
section "Cloning Secrets Manager"
SECRET_NAME="${TARGET_ENV}/app-secret"
if dryrun "Would create secret: $SECRET_NAME"; then :
else
  if aws secretsmanager describe-secret --region "$REGION" --secret-id "$SECRET_NAME" >/dev/null 2>&1; then
    warn "Secret already exists: $SECRET_NAME"
  else
    log "Searching for Base Secret (e.g., $SOURCE_ENV/app-secret)..."
    BASE_SECRET="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "${SOURCE_ENV}/app-secret" --query 'SecretString' --output text 2>/dev/null || echo "")"
    
    if [[ -z "$BASE_SECRET" ]]; then
      log "Base secret not found. Generating a new random secret..."
      BASE_SECRET="$(LC_ALL=C tr -dc 'A-Za-z0-9!@#$%^&*' < /dev/urandom | head -c 32 || true)"
      [[ -n "$BASE_SECRET" ]] || BASE_SECRET="$(openssl rand -base64 24)"
    fi
    
    log "Creating secret: $SECRET_NAME"
    aws secretsmanager create-secret \
      --region "$REGION" \
      --name "$SECRET_NAME" \
      --description "Secret for environment: $TARGET_ENV" \
      --secret-string "$BASE_SECRET" >/dev/null
    R_SECRET="$SECRET_NAME"
    ok "Secret created: $SECRET_NAME"
  fi
fi

# =============================================================================
#  Clone Cognito User Pool
# =============================================================================
section "Cloning Cognito User Pool"
POOL_NAME="${TARGET_ENV}-userpool"
CLIENT_NAME="${TARGET_ENV}-client"
USER_POOL_ID=""
APP_CLIENT_ID=""

if dryrun "Would find Cognito Pool with '$SOURCE_ENV', clone to '$POOL_NAME'"; then 
  USER_POOL_ID="dry-run-pool-id"
  APP_CLIENT_ID="dry-run-client-id"
else
  EXISTING_POOL="$(aws cognito-idp list-user-pools --region "$REGION" --max-results 60 --query "UserPools[?Name=='$POOL_NAME'].Id" --output text 2>/dev/null || true)"
  if [[ -n "$EXISTING_POOL" && "$EXISTING_POOL" != "None" ]]; then
    warn "User pool already exists: $EXISTING_POOL"
    USER_POOL_ID="$EXISTING_POOL"
  else
    log "Creating User Pool: $POOL_NAME"
    POOL_JSON="$(aws cognito-idp create-user-pool \
      --region "$REGION" \
      --pool-name "$POOL_NAME" \
      --auto-verified-attributes email \
      --username-attributes email \
      --mfa-configuration OFF \
      --policies 'PasswordPolicy={MinimumLength=8,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}')"
    USER_POOL_ID="$(jq -r '.UserPool.Id' <<< "$POOL_JSON")"
    R_POOL_ID="$USER_POOL_ID"
    ok "User pool created: $USER_POOL_ID"
  fi
  
  log "Creating App Client: $CLIENT_NAME"
  CLIENT_JSON="$(aws cognito-idp create-user-pool-client \
    --region "$REGION" \
    --user-pool-id "$USER_POOL_ID" \
    --client-name "$CLIENT_NAME" \
    --no-generate-secret \
    --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH ALLOW_ADMIN_USER_PASSWORD_AUTH 2>/dev/null || echo '{}')"
  APP_CLIENT_ID="$(jq -r '.UserPoolClient.ClientId // "error"' <<< "$CLIENT_JSON")"
  if [[ "$APP_CLIENT_ID" == "error" ]]; then
    warn "App client may already exist - fetching existing client..."
    APP_CLIENT_ID="$(aws cognito-idp list-user-pool-clients --region "$REGION" --user-pool-id "$USER_POOL_ID" --query 'UserPoolClients[0].ClientId' --output text)"
  fi
  ok "App client configured: $APP_CLIENT_ID"
fi

# =============================================================================
#  Clone Lambdas & Generate APIs
# =============================================================================
section "Cloning Lambdas & Wiring API Gateways"

declare -A CLONED_LAMBDAS
API_URLS=""

if dryrun "Would clone Lambdas and create REST APIs"; then :
else
  log "Searching for Lambdas matching '*${SOURCE_ENV}*'..."
  mapfile -t LAMBDAS < <(aws lambda list-functions --region "$REGION" --output json \
    | jq -r --arg s "$SOURCE_ENV" '.Functions[].FunctionName | select(contains($s))')
  
  if [[ ${#LAMBDAS[@]} -eq 0 || -z "${LAMBDAS[0]:-}" ]]; then
    warn "No Lambdas found matching $SOURCE_ENV."
  else
    for L_SOURCE in "${LAMBDAS[@]}"; do
      L_TARGET="${L_SOURCE//$SOURCE_ENV/$TARGET_ENV}"
      API_NAME="${L_TARGET}-api"
      
      # 1. Clone Lambda
      if aws lambda get-function --region "$REGION" --function-name "$L_TARGET" >/dev/null 2>&1; then
         warn "Lambda already exists: $L_TARGET"
         L_ARN="$(aws lambda get-function --region "$REGION" --function-name "$L_TARGET" --query 'Configuration.FunctionArn' --output text)"
      else
        log "Cloning Lambda: $L_SOURCE -> $L_TARGET"
        LFN="$(aws lambda get-function --region "$REGION" --function-name "$L_SOURCE" --output json)"
        LCFG="$(jq '.Configuration' <<< "$LFN")"
        
        LZIP="$TMP_DIR/lambda_$L_SOURCE.zip"
        curl -fsSL "$(jq -r '.Code.Location' <<< "$LFN")" -o "$LZIP"
        ROLE_ARN="$(jq -r '.Role' <<< "$LCFG")"
        
        L_CREATE_OUT="$(aws lambda create-function \
          --region        "$REGION" \
          --function-name "$L_TARGET" \
          --runtime       "$(jq -r '.Runtime'    <<< "$LCFG")" \
          --handler       "$(jq -r '.Handler'    <<< "$LCFG")" \
          --role          "$ROLE_ARN" \
          --zip-file      "fileb://$LZIP" \
          --timeout       "$(jq -r '.Timeout'    <<< "$LCFG")" \
          --memory-size   "$(jq -r '.MemorySize' <<< "$LCFG")" --output json)"
          
        R_LAMBDAS+=("$L_TARGET")
        aws lambda wait function-active-v2 --region "$REGION" --function-name "$L_TARGET"
        L_ARN="$(jq -r '.FunctionArn' <<< "$L_CREATE_OUT")"
        ok "Created Lambda: $L_TARGET"
      fi
      
      # 2. Create REST API Gateway
      log "Wiring REST API Gateway: $API_NAME"
      API_ID="$(aws apigateway create-rest-api \
        --region "$REGION" \
        --name "$API_NAME" \
        --description "REST API for $L_TARGET" \
        --endpoint-configuration types=REGIONAL \
        --query 'id' --output text)"
      R_APIS+=("$API_ID")
      
      ROOT_ID="$(aws apigateway get-resources --region "$REGION" --rest-api-id "$API_ID" --query 'items[?path==`/`].id' --output text)"
      PROXY_ID="$(aws apigateway create-resource --region "$REGION" --rest-api-id "$API_ID" --parent-id "$ROOT_ID" --path-part '{proxy+}' --query 'id' --output text)"
      
      aws apigateway put-method --region "$REGION" --rest-api-id "$API_ID" --resource-id "$PROXY_ID" --http-method ANY --authorization-type NONE >/dev/null
      aws apigateway put-integration --region "$REGION" --rest-api-id "$API_ID" --resource-id "$PROXY_ID" --http-method ANY --type AWS_PROXY --integration-http-method POST --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${L_ARN}/invocations" >/dev/null
      aws apigateway create-deployment --region "$REGION" --rest-api-id "$API_ID" --stage-name "$TARGET_ENV" >/dev/null
      
      aws lambda add-permission --region "$REGION" --function-name "$L_TARGET" --statement-id "apigw-${L_TARGET}" --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*" >/dev/null 2>&1 || true
      
      API_ENDPOINT="https://${API_ID}.execute-api.${REGION}.amazonaws.com/${TARGET_ENV}"
      API_URLS+="$API_ENDPOINT,"
      ok "Wired API: $API_ENDPOINT"

      # 3. Inject new Environment Variables into Lambda
      log "Updating environment variables in $L_TARGET..."
      BASE_ENV="$(aws lambda get-function --region "$REGION" --function-name "$L_SOURCE" --query 'Configuration.Environment.Variables' --output json 2>/dev/null || echo "{}")"
      MERGED="$(jq -n --argjson base "$BASE_ENV" \
        --arg env_name "$TARGET_ENV" \
        --arg region "$REGION" \
        --arg pool "$USER_POOL_ID" \
        --arg client "$APP_CLIENT_ID" \
        --arg secret "$SECRET_NAME" \
        --arg api "$API_ENDPOINT" \
        '$base + {
          ENV: $env_name,
          ENV_NAME: $env_name,
          REGION: $region,
          USER_POOL_ID: $pool,
          APP_CLIENT_ID: $client,
          SECRET_NAME: $secret,
          API_URL: $api
        }')"
      
      aws lambda update-function-configuration --region "$REGION" --function-name "$L_TARGET" --environment "{\"Variables\": $(jq -c '.' <<< "$MERGED")}" >/dev/null
      aws lambda wait function-updated-v2 --region "$REGION" --function-name "$L_TARGET"
    done
  fi
fi

# =============================================================================
#  Clone Amplify Branch
# =============================================================================
section "Amplify Branch Deployment"
BRANCH_ENV_VARS="$(jq -n -c \
  --arg env "$TARGET_ENV" \
  --arg pool "$USER_POOL_ID" \
  --arg client "$APP_CLIENT_ID" \
  --arg secret "$SECRET_NAME" \
  --arg urls "${API_URLS%,}" \
  '{
    ENV_NAME: $env,
    USER_POOL_ID: $pool,
    APP_CLIENT_ID: $client,
    SECRET_NAME: $secret,
    NEXT_PUBLIC_API_URLS: $urls
  }')"

if dryrun "Would create Amplify branch '$TARGET_ENV' on app $AMPLIFY_APP_ID"; then :
else
  if aws amplify get-branch --region "$REGION" --app-id "$AMPLIFY_APP_ID" --branch-name "$TARGET_ENV" >/dev/null 2>&1; then
    warn "Amplify branch '$TARGET_ENV' already exists."
  else
    log "Creating Amplify branch: $TARGET_ENV (app: $AMPLIFY_APP_ID)"
    aws amplify create-branch \
      --region "$REGION" \
      --app-id "$AMPLIFY_APP_ID" \
      --branch-name "$TARGET_ENV" \
      --stage DEVELOPMENT \
      --framework "Next.js - SSR" \
      --environment-variables "$BRANCH_ENV_VARS" >/dev/null
    R_BRANCH="$TARGET_ENV"
    R_BRANCH_APP="$AMPLIFY_APP_ID"
    ok "Amplify branch created."
  fi

  log "Triggering Amplify RELEASE deployment..."
  aws amplify start-job --region "$REGION" --app-id "$AMPLIFY_APP_ID" --branch-name "$TARGET_ENV" --job-type RELEASE >/dev/null 2>&1 || warn "Could not trigger deployment. You may need to connect the GitHub branch first via the AWS Console."
  ok "Deployment triggered."
fi

# =============================================================================
#  Update Subscriber Status
# =============================================================================
section "Update MarketplaceSubscribers"
if [[ "$REG_TOKEN" != "manual-token" ]]; then
  if dryrun "Would set isDeployed = true for $REG_TOKEN"; then :
  else
    log "Updating isDeployed to true for regToken=$REG_TOKEN..."
    aws dynamodb update-item \
      --region "$REGION" \
      --table-name "MarketplaceSubscribers" \
      --key "{\"regToken\": {\"S\": \"$REG_TOKEN\"}}" \
      --update-expression "SET isDeployed = :v1" \
      --expression-attribute-values '{":v1":{"S":"true"}}' 2>/dev/null || aws dynamodb update-item \
      --region "$REGION" \
      --table-name "MarketplaceSubscribers" \
      --key "{\"regToken\": {\"S\": \"$REG_TOKEN\"}}" \
      --update-expression "SET isDeployed = :v1" \
      --expression-attribute-values '{":v1":{"BOOL":true}}'
    ok "Subscriber updated successfully."
  fi
fi

trap cleanup EXIT

printf "\n${GREEN}${BOLD}  ✔  Environment '$TARGET_ENV' cloned successfully!${RESET}\n\n"

# =============================================================================
#  Seed DynamoDB Tables
# =============================================================================
section "Seeding Initial Tenant Data"
if dryrun "Would execute seed_tenant_data.py for $TARGET_ENV"; then :
else
  log "Seeding configuration and admin user..."
  python3 /home/user/Downloads/Automation\ \ 2/Automation\ /aws-marketplace-soft-launch/seed_tenant_data.py --env "$TARGET_ENV"
  ok "Database seeding completed."
fi

# =============================================================================
#  Execute E2E Role Validation & UI Tests
# =============================================================================
section "E2E Role Validation Tests"
log "Running automated E2E tests for $TARGET_ENV..."

# WARNING: Set your actual test password below, or ensure it's exported in your environment!
TEST_PASSWORD="${TEST_PASSWORD:-REPLACE_WITH_YOUR_PASSWORD}"

if dryrun "Would execute E2E test for $TARGET_ENV"; then :
else
  python3 /home/user/Downloads/Automation\ \ 2/Automation\ /aws-marketplace-soft-launch/e2e_role_validation_test.py \
    --env "$TARGET_ENV" \
    --url "https://${TARGET_ENV}.d246slprgvqfid.amplifyapp.com" \
    --username "admin@${TARGET_ENV}.com" \
    --password "$TEST_PASSWORD"

  if [[ $? -eq 0 ]]; then
    ok "E2E Validation Passed!"
  else
    warn "E2E Validation Failed!"
  fi
fi

