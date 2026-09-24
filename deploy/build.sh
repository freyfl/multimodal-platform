#!/bin/bash
# Always build the current frontend; no reuse of a previous dist.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
check_node
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"
cd "$PROJECT_ROOT/frontend"
[ -f package-lock.json ] || fail "frontend/package-lock.json is required for npm ci."
[ ! -L dist ] || fail "Refusing a symlinked frontend/dist."

# Remove only generated assets; a failed install/build cannot leave a releasable old dist.
rm -rf -- dist
npm ci --include=dev --registry="$NPM_REGISTRY"
npm run build
[ -s dist/index.html ] || fail "Build did not produce frontend/dist/index.html."
printf 'Fresh frontend build completed.\n'
