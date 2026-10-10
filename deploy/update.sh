#!/bin/bash
# In-place upgrade of an existing deployment from a release archive built by deploy/pack.sh.
# Usage (on the server, from the deployed project root):
#   APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/update.sh /path/to/multimodal-platform-YYYYMMDD-release.tar.gz
#
# Never reads, sources, creates or overwrites backend/.env; never touches data volumes,
# backend/data, logs or annotation storage. Does not rebuild the frontend: the archive
# already carries a verified frontend/dist. A rollback archive is written to releases/.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
[ "$#" -eq 1 ] || fail "Usage: deploy/update.sh <release.tar.gz>"
ARCHIVE="$1"
[[ "$ARCHIVE" = /* ]] || ARCHIVE="$(pwd)/$ARCHIVE"
[ -f "$ARCHIVE" ] && [ ! -L "$ARCHIVE" ] || fail "Release archive not found or is a symlink: $ARCHIVE"
require_command tar
require_command curl
check_venv
[ -f "$PROJECT_ROOT/backend/.env" ] || fail "backend/.env is missing; this script only upgrades an installed deployment."

# List once: with pipefail, `tar | grep -q` would fail on SIGPIPE even when the entry exists.
LISTING="$(tar -tzf "$ARCHIVE")" || fail "Cannot read archive: $ARCHIVE"
# The archive has exactly one top-level directory; its name may differ from ours.
TOP="$(printf '%s\n' "$LISTING" | awk -F/ 'NF{print $1}' | sort -u)"
[ "$(printf '%s\n' "$TOP" | wc -l)" -eq 1 ] || fail "Archive must contain a single top-level directory."
has_entry() { printf '%s\n' "$LISTING" | grep -qx -- "$1"; }
has_entry "$TOP/frontend/dist/index.html" || fail "Archive lacks a built frontend (frontend/dist/index.html)."
has_entry "$TOP/backend/requirements.txt" || fail "Archive lacks backend/requirements.txt."
! has_entry "$TOP/backend/.env" || fail "Refusing an archive that contains backend/.env."

STAMP="$(date +%Y%m%d-%H%M%S)"
RELEASES="$PROJECT_ROOT/releases"
mkdir -p "$RELEASES"
BACKUP="$RELEASES/rollback-$STAMP.tar.gz"
printf 'Stopping application (infrastructure containers keep running)...\n'
bash "$SCRIPT_DIR/stop.sh"

printf 'Writing rollback archive %s\n' "$BACKUP"
# Code and static assets only; data, env, venv, node_modules, logs and releases stay in place.
ROLLBACK_PATHS=()
for entry in backend frontend deploy docs README.md; do
    [ -e "$PROJECT_ROOT/$entry" ] && ROLLBACK_PATHS+=("$entry")
done
[ "${#ROLLBACK_PATHS[@]}" -gt 0 ] || fail "Nothing to back up under $PROJECT_ROOT."
tar -czf "$BACKUP" -C "$PROJECT_ROOT" \
    --exclude='backend/venv' --exclude='backend/data' --exclude='backend/.env' \
    --exclude='frontend/node_modules' --exclude='logs' --exclude='releases' \
    --exclude='__pycache__' --exclude='.pytest_cache' \
    "${ROLLBACK_PATHS[@]}" || fail "Rollback archive failed; nothing was changed."

printf 'Replacing generated frontend assets...\n'
rm -rf -- "$PROJECT_ROOT/frontend/dist"
printf 'Extracting release...\n'
tar -xzf "$ARCHIVE" -C "$PROJECT_ROOT" --strip-components=1 --no-same-owner \
    --exclude="$TOP/backend/.env" --exclude="$TOP/backend/data" --exclude="$TOP/logs"
[ -s "$PROJECT_ROOT/frontend/dist/index.html" ] || fail "frontend/dist missing after extraction."

printf 'Syncing Python dependencies into the existing venv...\n'
VENV_PY="$PROJECT_ROOT/backend/venv/bin/python"
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || fail "backend/venv has no pip and ensurepip failed; recreate it with deploy/install.sh."
fi
"$VENV_PY" -m pip install --quiet -r "$PROJECT_ROOT/backend/requirements.txt"
find "$PROJECT_ROOT/backend" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

printf 'Starting application...\n'
APP_ENV_FILE="${APP_ENV_FILE:-$PROJECT_ROOT/backend/.env}" bash "$SCRIPT_DIR/start.sh" --daemon
printf 'Upgrade finished. Rollback: stop.sh, then extract %s over the project root and start.sh again.\n' "$BACKUP"
