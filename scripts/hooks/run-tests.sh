#!/bin/bash
# Pre-push hook. Delegates to scripts/validate.sh so the pre-push gate and
# `make validate` never drift out of sync.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! "$REPO_ROOT/scripts/validate.sh"; then
    echo "❌ Validation failed. Fix lint/format/tests before pushing."
    exit 1
fi

exit 0
