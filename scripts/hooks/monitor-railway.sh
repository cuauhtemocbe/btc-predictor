#!/bin/bash
#
# Monitor Railway deployment after git push
#
# This script monitors Railway services until they complete deployment.
# It checks the status of btc-predictor, weekly-predictor, daily, and fetch-price services.
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

# Configuration
TIMEOUT_SECONDS=300  # 5 minutes max
CHECK_INTERVAL=5     # Check every 5 seconds
SERVICES=("btc-predictor" "weekly-predictor" "daily" "fetch-price")

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
for service in "${SERVICES[@]}"; do
    deployment_id=$(railway service list 2>/dev/null | grep -A3 "^$service$" | grep "deployment ID:" | awk '{print $3}')
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

    for service in "${SERVICES[@]}"; do
        # Get current status
        status=$(railway service list 2>/dev/null | grep -A1 "^$service$" | grep "status:" | sed 's/.*status:[[:space:]]*//')
        deployment_id=$(railway service list 2>/dev/null | grep -A3 "^$service$" | grep "deployment ID:" | awk '{print $3}')

        # Check if deployment changed
        if [[ "${INITIAL_DEPLOYMENTS[$service]}" != "$deployment_id" ]]; then
            status_changed=true
        fi

        # Check if still building/deploying
        if echo "$status" | grep -qE "Building|Deploying|Queued"; then
            all_online=false
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
    for service in "${SERVICES[@]}"; do
        status=$(railway service list 2>/dev/null | grep -A1 "^$service$" | grep "status:" | sed 's/.*status:[[:space:]]*//' | cut -d' ' -f1-2)
        log "  ${GREEN}●${NC} $service: $status"
    done

    # Check for migration in logs
    log "\n${BLUE}🔍 Checking migration logs...${NC}"
    if railway logs --service btc-predictor 2>/dev/null | grep -q "add timeframe column"; then
        log "${GREEN}✅ Migration 'add timeframe column' detected${NC}"
    fi

    # Show dashboard URL
    log "\n${BLUE}🌐 Dashboard:${NC}"
    url=$(railway status 2>/dev/null | grep "btc-predictor:" | grep -oP 'https://[^\s]+')
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
