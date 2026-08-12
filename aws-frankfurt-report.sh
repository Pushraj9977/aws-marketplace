#!/usr/bin/env bash
# =============================================================================
#  aws-frankfurt-report.sh  —  Full AWS Resource Report: eu-central-1 (Frankfurt)
#
#  Scans ALL key services and outputs a complete inventory with resource names.
#
#  Usage:
#    ./aws-frankfurt-report.sh
#    ./aws-frankfurt-report.sh --output report.txt   (also saves to file)
# =============================================================================

set -euo pipefail
REGION="eu-central-1"
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT_FILE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

log()     { printf "${GREEN}[%s]${RESET} %s\n" "$(date '+%H:%M:%S')" "$*"; }
section() { printf "\n${BOLD}${CYAN}  ▶  %s${RESET}\n  %s\n" "$1" "$(printf '%.0s─' {1..60})"; }
row()     { printf "  ${GREEN}✔${RESET}  %-45s  ${DIM}%s${RESET}\n" "$1" "$2"; }
empty()   { printf "  ${YELLOW}—${RESET}  %s\n" "$1"; }
err()     { printf "  ${RED}✖${RESET}  %s\n" "$1" >&2; }

# Redirect to file if requested
if [[ -n "$OUTPUT_FILE" ]]; then
  exec > >(tee "$OUTPUT_FILE") 2>&1
fi

# ── Banner ────────────────────────────────────────────────────────────────────
clear 2>/dev/null || true
printf "${CYAN}${BOLD}"
printf "  ╔══════════════════════════════════════════════════════════════╗\n"
printf "  ║      AWS Full Resource Report — Frankfurt (eu-central-1)     ║\n"
printf "  ║                 Generated: %-34s║\n" "$(date '+%Y-%m-%d %H:%M:%S')"
printf "  ╚══════════════════════════════════════════════════════════════╝\n"
printf "${RESET}\n"

# ── Validate Credentials ──────────────────────────────────────────────────────
CALLER="$(aws sts get-caller-identity 2>/dev/null)" || { printf "${RED}✖  AWS credentials not configured.${RESET}\n"; exit 1; }
ACCOUNT_ID="$(jq -r '.Account' <<< "$CALLER")"
CALLER_ARN="$(jq -r '.Arn' <<< "$CALLER")"
printf "  ${BOLD}Account:${RESET}  $ACCOUNT_ID\n"
printf "  ${BOLD}Identity:${RESET} $CALLER_ARN\n"
printf "  ${BOLD}Region:${RESET}   $REGION\n\n"

# =============================================================================
#  1. LAMBDA FUNCTIONS
# =============================================================================
section "Lambda Functions"
log "Fetching Lambda functions..."
LAMBDAS="$(aws lambda list-functions --region "$REGION" --output json 2>/dev/null)"
LAMBDA_COUNT="$(jq '.Functions | length' <<< "$LAMBDAS")"
if [[ "$LAMBDA_COUNT" -eq 0 ]]; then
  empty "No Lambda functions found."
else
  printf "  ${BOLD}%-45s  %-14s  %-8s  %s${RESET}\n" "Function Name" "Runtime" "Memory" "Timeout"
  printf "  %s\n" "$(printf '%.0s─' {1..85})"
  jq -r '.Functions[] | [.FunctionName, (.Runtime // "N/A"), ((.MemorySize | tostring) + " MB"), ((.Timeout | tostring) + "s")] | @tsv' <<< "$LAMBDAS" \
  | sort | while IFS=$'\t' read -r name runtime mem timeout; do
      printf "  ${GREEN}✔${RESET}  %-45s  %-14s  %-8s  %s\n" "$name" "$runtime" "$mem" "$timeout"
    done
fi
printf "\n  ${BOLD}Total Lambda Functions: ${GREEN}$LAMBDA_COUNT${RESET}\n"

# =============================================================================
#  2. DYNAMODB TABLES
# =============================================================================
section "DynamoDB Tables"
log "Fetching DynamoDB tables..."
TABLES="$(aws dynamodb list-tables --region "$REGION" --output json 2>/dev/null)"
TABLE_COUNT="$(jq '.TableNames | length' <<< "$TABLES")"
if [[ "$TABLE_COUNT" -eq 0 ]]; then
  empty "No DynamoDB tables found."
else
  printf "  ${BOLD}%-50s  %s${RESET}\n" "Table Name" "Status"
  printf "  %s\n" "$(printf '%.0s─' {1..65})"
  jq -r '.TableNames[]' <<< "$TABLES" | sort | while read -r tbl; do
    STATUS="$(aws dynamodb describe-table --region "$REGION" --table-name "$tbl" --query 'Table.TableStatus' --output text 2>/dev/null || echo 'UNKNOWN')"
    printf "  ${GREEN}✔${RESET}  %-50s  ${GREEN}%s${RESET}\n" "$tbl" "$STATUS"
  done
fi
printf "\n  ${BOLD}Total DynamoDB Tables: ${GREEN}$TABLE_COUNT${RESET}\n"

# =============================================================================
#  3. API GATEWAY (REST — v1)
# =============================================================================
section "API Gateway — REST APIs (v1)"
log "Fetching REST APIs..."
REST_APIS="$(aws apigateway get-rest-apis --region "$REGION" --output json 2>/dev/null)"
REST_COUNT="$(jq '.items | length' <<< "$REST_APIS")"
if [[ "$REST_COUNT" -eq 0 ]]; then
  empty "No REST APIs found."
else
  printf "  ${BOLD}%-14s  %-45s  %s${RESET}\n" "API ID" "Name" "Endpoint"
  printf "  %s\n" "$(printf '%.0s─' {1..85})"
  jq -r '.items[] | [.id, .name] | @tsv' <<< "$REST_APIS" | sort -t$'\t' -k2 | while IFS=$'\t' read -r id name; do
    URL="https://${id}.execute-api.${REGION}.amazonaws.com"
    printf "  ${GREEN}✔${RESET}  %-14s  %-45s  ${DIM}%s${RESET}\n" "$id" "$name" "$URL"
  done
fi
printf "\n  ${BOLD}Total REST APIs: ${GREEN}$REST_COUNT${RESET}\n"

# =============================================================================
#  4. API GATEWAY (HTTP — v2)
# =============================================================================
section "API Gateway — HTTP APIs (v2)"
log "Fetching HTTP APIs..."
HTTP_APIS="$(aws apigatewayv2 get-apis --region "$REGION" --output json 2>/dev/null)"
HTTP_COUNT="$(jq '.Items | length' <<< "$HTTP_APIS")"
if [[ "$HTTP_COUNT" -eq 0 ]]; then
  empty "No HTTP APIs found."
else
  printf "  ${BOLD}%-14s  %-45s  %s${RESET}\n" "API ID" "Name" "Endpoint"
  printf "  %s\n" "$(printf '%.0s─' {1..85})"
  jq -r '.Items[] | [.ApiId, .Name, .ApiEndpoint] | @tsv' <<< "$HTTP_APIS" | sort -t$'\t' -k2 | while IFS=$'\t' read -r id name endpoint; do
    printf "  ${GREEN}✔${RESET}  %-14s  %-45s  ${DIM}%s${RESET}\n" "$id" "$name" "$endpoint"
  done
fi
printf "\n  ${BOLD}Total HTTP APIs: ${GREEN}$HTTP_COUNT${RESET}\n"

# =============================================================================
#  5. COGNITO USER POOLS
# =============================================================================
section "Cognito User Pools"
log "Fetching Cognito User Pools..."
POOLS="$(aws cognito-idp list-user-pools --region "$REGION" --max-results 60 --output json 2>/dev/null)"
POOL_COUNT="$(jq '.UserPools | length' <<< "$POOLS")"
if [[ "$POOL_COUNT" -eq 0 ]]; then
  empty "No Cognito User Pools found."
else
  printf "  ${BOLD}%-30s  %-25s  %s${RESET}\n" "Pool Name" "Pool ID" "Created"
  printf "  %s\n" "$(printf '%.0s─' {1..85})"
  jq -r '.UserPools[] | [.Name, .Id, .CreationDate] | @tsv' <<< "$POOLS" | sort | while IFS=$'\t' read -r name id created; do
    created_fmt="${created%%T*}"
    printf "  ${GREEN}✔${RESET}  %-30s  %-25s  %s\n" "$name" "$id" "$created_fmt"
  done
fi
printf "\n  ${BOLD}Total Cognito User Pools: ${GREEN}$POOL_COUNT${RESET}\n"

# =============================================================================
#  6. SECRETS MANAGER
# =============================================================================
section "Secrets Manager"
log "Fetching Secrets..."
SECRETS="$(aws secretsmanager list-secrets --region "$REGION" --output json 2>/dev/null)"
SECRET_COUNT="$(jq '.SecretList | length' <<< "$SECRETS")"
if [[ "$SECRET_COUNT" -eq 0 ]]; then
  empty "No secrets found."
else
  printf "  ${BOLD}%-50s  %s${RESET}\n" "Secret Name" "Last Changed"
  printf "  %s\n" "$(printf '%.0s─' {1..75})"
  jq -r '.SecretList[] | [.Name, (.LastChangedDate // .CreatedDate // "N/A" | tostring)] | @tsv' <<< "$SECRETS" | sort | while IFS=$'\t' read -r name changed; do
    changed_fmt="${changed%%T*}"
    printf "  ${GREEN}✔${RESET}  %-50s  %s\n" "$name" "$changed_fmt"
  done
fi
printf "\n  ${BOLD}Total Secrets: ${GREEN}$SECRET_COUNT${RESET}\n"

# =============================================================================
#  7. AMPLIFY APPS
# =============================================================================
section "Amplify Apps & Branches"
log "Fetching Amplify Apps..."
AMPLIFY_APPS="$(aws amplify list-apps --region "$REGION" --output json 2>/dev/null)"
APP_COUNT="$(jq '.apps | length' <<< "$AMPLIFY_APPS")"
if [[ "$APP_COUNT" -eq 0 ]]; then
  empty "No Amplify Apps found."
else
  jq -r '.apps[] | [.appId, .name, .platform] | @tsv' <<< "$AMPLIFY_APPS" | sort -t$'\t' -k2 | while IFS=$'\t' read -r appid name platform; do
    printf "\n  ${BOLD}${BLUE}App:${RESET} %-30s ${DIM}(ID: %s | Platform: %s)${RESET}\n" "$name" "$appid" "$platform"
    printf "  ${BOLD}%-5s  %-30s  %-12s  %s${RESET}\n" "Stage" "Branch Name" "Status" "Last Deploy"
    printf "  %s\n" "$(printf '%.0s─' {1..75})"
    BRANCHES="$(aws amplify list-branches --region "$REGION" --app-id "$appid" --output json 2>/dev/null)"
    BRANCH_COUNT="$(jq '.branches | length' <<< "$BRANCHES")"
    if [[ "$BRANCH_COUNT" -eq 0 ]]; then
      printf "  ${YELLOW}—${RESET}  No branches found.\n"
    else
      jq -r '.branches[] | [(.stage // "N/A"), .branchName, (.activeJobId // "N/A"), (.updateTime // "N/A")] | @tsv' <<< "$BRANCHES" | sort -t$'\t' -k2 | while IFS=$'\t' read -r stage branchname jobid updated; do
        updated_fmt="${updated%%T*}"
        printf "  ${GREEN}✔${RESET}  %-5s  %-30s  %-12s  %s\n" "$stage" "$branchname" "$jobid" "$updated_fmt"
      done
    fi
  done
fi
printf "\n  ${BOLD}Total Amplify Apps: ${GREEN}$APP_COUNT${RESET}\n"

# =============================================================================
#  8. IAM ROLES (Lambda related)
# =============================================================================
section "IAM Roles (Lambda & Amplify)"
log "Fetching relevant IAM Roles..."
IAM_ROLES="$(aws iam list-roles --output json 2>/dev/null)"
LAMBDA_ROLES="$(jq -r '.Roles[] | select(.RoleName | test("lambda|amplify|backend"; "i")) | [.RoleName, .Arn, .CreateDate] | @tsv' <<< "$IAM_ROLES")"
ROLE_COUNT="$(echo "$LAMBDA_ROLES" | grep -c '^' 2>/dev/null || true)"
if [[ -z "$LAMBDA_ROLES" ]]; then
  empty "No Lambda/Amplify related IAM roles found."
else
  printf "  ${BOLD}%-45s  %s${RESET}\n" "Role Name" "Created"
  printf "  %s\n" "$(printf '%.0s─' {1..75})"
  echo "$LAMBDA_ROLES" | sort | while IFS=$'\t' read -r name arn created; do
    created_fmt="${created%%T*}"
    printf "  ${GREEN}✔${RESET}  %-45s  %s\n" "$name" "$created_fmt"
  done
fi
printf "\n  ${BOLD}Total Roles Found: ${GREEN}$ROLE_COUNT${RESET}\n"

# =============================================================================
#  9. S3 BUCKETS (Global, listing all)
# =============================================================================
section "S3 Buckets (All Regions)"
log "Fetching S3 Buckets..."
S3_BUCKETS="$(aws s3api list-buckets --output json 2>/dev/null)"
S3_COUNT="$(jq '.Buckets | length' <<< "$S3_BUCKETS")"
if [[ "$S3_COUNT" -eq 0 ]]; then
  empty "No S3 buckets found."
else
  printf "  ${BOLD}%-55s  %s${RESET}\n" "Bucket Name" "Created"
  printf "  %s\n" "$(printf '%.0s─' {1..75})"
  jq -r '.Buckets[] | [.Name, .CreationDate] | @tsv' <<< "$S3_BUCKETS" | sort | while IFS=$'\t' read -r name created; do
    created_fmt="${created%%T*}"
    printf "  ${GREEN}✔${RESET}  %-55s  %s\n" "$name" "$created_fmt"
  done
fi
printf "\n  ${BOLD}Total S3 Buckets: ${GREEN}$S3_COUNT${RESET}\n"

# =============================================================================
#  10. CloudWatch Log Groups
# =============================================================================
section "CloudWatch Log Groups (Lambda)"
log "Fetching Lambda Log Groups..."
LOG_GROUPS="$(aws logs describe-log-groups --region "$REGION" --log-group-name-prefix "/aws/lambda/" --output json 2>/dev/null)"
LOG_COUNT="$(jq '.logGroups | length' <<< "$LOG_GROUPS")"
if [[ "$LOG_COUNT" -eq 0 ]]; then
  empty "No Lambda log groups found."
else
  printf "  ${BOLD}%-55s  %s${RESET}\n" "Log Group" "Retention"
  printf "  %s\n" "$(printf '%.0s─' {1..75})"
  jq -r '.logGroups[] | [.logGroupName, ((.retentionInDays // "Never") | tostring)] | @tsv' <<< "$LOG_GROUPS" | sort | while IFS=$'\t' read -r name retention; do
    printf "  ${GREEN}✔${RESET}  %-55s  %s days\n" "$name" "$retention"
  done
fi
printf "\n  ${BOLD}Total Log Groups: ${GREEN}$LOG_COUNT${RESET}\n"

# =============================================================================
#  FINAL SUMMARY
# =============================================================================
printf "\n${BOLD}${CYAN}  ▶  SUMMARY — Frankfurt (eu-central-1)${RESET}\n"
printf "  %s\n" "$(printf '%.0s═' {1..60})"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "Lambda Functions:"      "$LAMBDA_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "DynamoDB Tables:"       "$TABLE_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "REST APIs (v1):"        "$REST_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "HTTP APIs (v2):"        "$HTTP_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "Cognito User Pools:"    "$POOL_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "Secrets Manager:"       "$SECRET_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "Amplify Apps:"          "$APP_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "S3 Buckets:"            "$S3_COUNT"
printf "  ${BOLD}%-35s  ${GREEN}%s${RESET}\n"  "CloudWatch Log Groups:" "$LOG_COUNT"
printf "  %s\n" "$(printf '%.0s═' {1..60})"
printf "  ${DIM}Report generated at: $(date '+%Y-%m-%d %H:%M:%S')${RESET}\n\n"

[[ -n "$OUTPUT_FILE" ]] && printf "  ${YELLOW}Report also saved to: ${BOLD}$OUTPUT_FILE${RESET}\n\n"
