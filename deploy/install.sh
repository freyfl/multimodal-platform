#!/bin/bash
# Install on ECS. Never read, source, create or overwrite backend/.env.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
check_python
check_node
check_docker_compose
check_media_tools
[ -f "$PROJECT_ROOT/backend/requirements.txt" ] || fail "Missing backend/requirements.txt."
[ -f "$PROJECT_ROOT/backend/.env.example" ] || fail "Missing backend/.env.example."

if [ ! -d "$PROJECT_ROOT/backend/venv" ]; then
    "$PYTHON_BIN" -m venv "$PROJECT_ROOT/backend/venv"
fi
check_venv
"$PROJECT_ROOT/backend/venv/bin/python" -m pip install --upgrade pip
"$PROJECT_ROOT/backend/venv/bin/python" -m pip install -r "$PROJECT_ROOT/backend/requirements.txt"
bash "$SCRIPT_DIR/build.sh"
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/backend/data"
printf '%s\n' \
    "Dependencies installed and frontend rebuilt; infrastructure was not started." \
    "Provision backend/.env from backend/.env.example securely on the target ECS." \
    "No configuration file was read or changed; no database initialization was run." \
    "Provision private annotation storage and a separate work directory outside this release." \
    "After configuration, deploy/start.sh starts local MySQL/Milvus before the application."
