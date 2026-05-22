#!/bin/bash
#
# Install git hooks for BTC Predictor
#
# This script installs:
#   - Pre-commit hooks (via pre-commit framework)
#   - Post-push hook (native git hook for Railway monitoring)
#
# Usage:
#   ./scripts/hooks/install.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔧 Installing git hooks for BTC Predictor...${NC}\n"

# Check if we're in a git repository
if [[ ! -d .git ]]; then
    echo -e "${RED}❌ Not in a git repository${NC}"
    echo "Run this script from the repository root"
    exit 1
fi

# 1. Install pre-commit framework hooks
echo -e "${BLUE}📋 Step 1: Installing pre-commit framework hooks...${NC}"

if ! command -v pre-commit &> /dev/null; then
    echo -e "${YELLOW}⚠️  pre-commit not found. Install with:${NC}"
    echo "  pip install pre-commit"
    echo ""
    read -p "Install now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip install pre-commit
    else
        echo -e "${RED}❌ Skipping pre-commit installation${NC}"
    fi
fi

if command -v pre-commit &> /dev/null; then
    echo "Installing pre-commit hooks..."
    pre-commit install --install-hooks
    pre-commit install --hook-type pre-push
    echo -e "${GREEN}✅ Pre-commit hooks installed${NC}"
else
    echo -e "${YELLOW}⚠️  Pre-commit hooks skipped${NC}"
fi

echo ""

# 2. Install post-push hook
echo -e "${BLUE}📋 Step 2: Installing post-push hook (Railway monitoring)...${NC}"

HOOK_SOURCE="scripts/hooks/post-push"
HOOK_TARGET=".git/hooks/post-push"

if [[ ! -f "$HOOK_SOURCE" ]]; then
    echo -e "${RED}❌ Hook source not found: $HOOK_SOURCE${NC}"
    exit 1
fi

# Backup existing hook if present
if [[ -f "$HOOK_TARGET" ]]; then
    echo -e "${YELLOW}⚠️  Existing post-push hook found${NC}"
    cp "$HOOK_TARGET" "$HOOK_TARGET.backup.$(date +%s)"
    echo "Backed up to: $HOOK_TARGET.backup.*"
fi

# Copy hook
cp "$HOOK_SOURCE" "$HOOK_TARGET"
chmod +x "$HOOK_TARGET"

echo -e "${GREEN}✅ Post-push hook installed${NC}"
echo ""

# 3. Verify Railway CLI (optional)
echo -e "${BLUE}📋 Step 3: Verifying Railway CLI...${NC}"

if ! command -v railway &> /dev/null; then
    echo -e "${YELLOW}⚠️  Railway CLI not found${NC}"
    echo "The post-push hook needs Railway CLI to monitor deployments."
    echo ""
    echo "Install with:"
    echo "  npm install -g @railway/cli"
    echo ""
    echo "Or download from: https://docs.railway.app/develop/cli"
else
    echo -e "${GREEN}✅ Railway CLI found${NC}"

    # Check if logged in
    if railway whoami &> /dev/null; then
        USER=$(railway whoami 2>&1 | head -1)
        echo -e "${GREEN}✅ Logged in as: $USER${NC}"
    else
        echo -e "${YELLOW}⚠️  Not logged in to Railway${NC}"
        echo "Run: railway login"
    fi
fi

echo ""
echo -e "${GREEN}✨ Git hooks installation complete!${NC}"
echo ""
echo -e "${BLUE}Installed hooks:${NC}"
echo "  • Pre-commit: Ruff lint + format"
echo "  • Pre-push: Pytest with 90% coverage"
echo "  • Post-push: Railway deployment monitoring"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Push to main: git push origin main"
echo "  2. Hook will automatically monitor Railway deployment"
echo "  3. Or run manually: ./scripts/hooks/monitor-railway.sh"
echo ""
