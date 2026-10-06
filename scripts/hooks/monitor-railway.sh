#!/bin/bash
#
# Monitor Railway deployment after git push
#
# This script monitors Railway services until they complete deployment.
# It checks the status of btc-predictor, daily, and fetch-price services.
#
# Usage:
#   ./scripts/hooks/monitor-railway.sh [--silent]
#
# Options:
#   --silent    Suppress output (for background monitoring)
#
# Exit codes:
#   0 - All services deployed successfully
#   1 - Deployment failed or timeout
#   2 - Railway CLI not available

set -e

# Configuration (env overrides exist so the script can be tested with a stub)
TIMEOUT_SECONDS=${MONITOR_TIMEOUT_SECONDS:-420}  # 7 minutes max
CHECK_INTERVAL=${MONITOR_CHECK_INTERVAL:-5}      # Check every 5 seconds
SERVICES=("btc-predictor" "daily" "fetch-price")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SILENT=false
if [[ "$1" == "--silent" ]]; then
    SILENT=true
fi

log() {
    if [[ "$SILENT" == "false" ]]; then
        echo -e "$1"
    fi
}

# Print one field of a service's block from `railway service list` output.
#
# A block starts at a line equal to the service name and runs until the next
# unindented line. Each block has a different number of optional fields
# (url, replicas, volume...), so the field is found by its label, never by a
# line offset from the service name.
#
# Usage: service_field <service> <label> <snapshot>
service_field() {
    local service="$1" label="$2" snapshot="$3"
    awk -v service="$service" -v label="$label" '
        /^[^[:space:]]/ { in_block = ($0 == service); next }
        in_block {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            prefix = label ":"
            if (index(line, prefix) == 1) {
                value = substr(line, length(prefix) + 1)
                sub(/^[[:space:]]+/, "", value)
                print value
                exit
            }
        }
    ' <<< "$snapshot"
}

# Allow tests to source the helpers without running the monitor
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

# Check if Railway CLI is available
if ! command -v railway &> /dev/null; then
    log "${RED}❌ Railway CLI not found${NC}"
    log "Install with: npm install -g @railway/cli"
    exit 2
fi

# Check if logged in
if ! railway whoami &> /dev/null; then
    log "${RED}❌ Not logged in to Railway${NC}"
    log "Run: railway login"
    exit 2
fi

log "${BLUE}🚀 Monitoring Railway deployment...${NC}\n"

# Get initial deployment IDs
declare -A INITIAL_DEPLOYMENTS
snapshot=$(railway service list 2>/dev/null || true)
for service in "${SERVICES[@]}"; do
    deployment_id=$(service_field "$service" "deployment ID" "$snapshot")
    INITIAL_DEPLOYMENTS[$service]=$deployment_id
    log "📦 $service: ${deployment_id:0:8}..."
done

log ""

# Monitor loop
elapsed=0
all_deployed=false

while [[ $elapsed -lt $TIMEOUT_SECONDS ]]; do
    sleep $CHECK_INTERVAL
    elapsed=$((elapsed + CHECK_INTERVAL))

    all_online=true
    status_changed=false
    snapshot=$(railway service list 2>/dev/null || true)

    for service in "${SERVICES[@]}"; do
        status=$(service_field "$service" "status" "$snapshot")
        deployment_id=$(service_field "$service" "deployment ID" "$snapshot")

        # Check if deployment changed
        if [[ "${INITIAL_DEPLOYMENTS[$service]}" != "$deployment_id" ]]; then
            status_changed=true
        fi

        # Check if still building/deploying
        if echo "$status" | grep -qE "Building|Deploying|Queued|Initializing|Waiting"; then
            all_online=false
        fi

        # A failed deployment will never come online: stop waiting
        if echo "$status" | grep -qE "Failed|Crashed"; then
            log "\n${RED}❌ $service deployment failed: $status${NC}"
            exit 1
        fi
    done

    if [[ "$all_online" == "true" && "$status_changed" == "true" ]]; then
        all_deployed=true
        break
    fi

    if [[ "$SILENT" == "false" ]]; then
        printf "\r⏳ Waiting for deployment... ${elapsed}s / ${TIMEOUT_SECONDS}s"
    fi
done

log "\n"

# Final status check
if [[ "$all_deployed" == "true" ]]; then
    log "${GREEN}✅ All services deployed successfully!${NC}\n"

    # Show final status
    log "${BLUE}📊 Final Status:${NC}"
    snapshot=$(railway service list 2>/dev/null || true)
    for service in "${SERVICES[@]}"; do
        status=$(service_field "$service" "status" "$snapshot" | cut -d' ' -f1-2)
        log "  ${GREEN}●${NC} $service: $status"
    done

    # Check for migration in logs
    log "\n${BLUE}🔍 Checking migration logs...${NC}"
    if railway logs --service btc-predictor 2>/dev/null | grep -q "add timeframe column"; then
        log "${GREEN}✅ Migration 'add timeframe column' detected${NC}"
    fi

    # Show dashboard URL
    log "\n${BLUE}🌐 Dashboard:${NC}"
    url=$(railway status 2>/dev/null | grep "btc-predictor:" | grep -oP 'https://[^\s]+' || true)
    if [[ -n "$url" ]]; then
        log "  $url"
    fi

    log "\n${GREEN}✨ Deployment complete!${NC}"
    exit 0
else
    log "${RED}❌ Deployment timeout after ${TIMEOUT_SECONDS}s${NC}"
    log "${YELLOW}⚠️  Services may still be deploying. Check manually:${NC}"
    log "  railway status"
    exit 1
fi
