#!/bin/bash
# One application worker: in-memory tasks are not a distributed queue.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
[ "$#" -le 1 ] || fail "Usage: deploy/start.sh [--daemon]"
MODE="${1:-}"
[[ -z "$MODE" || "$MODE" = "--daemon" ]] || fail "Usage: deploy/start.sh [--daemon]"
check_node
check_venv
check_media_tools
"$PROJECT_ROOT/backend/venv/bin/python" -c 'from PIL import Image, ImageOps' ||
    fail "Pillow is required; run deploy/install.sh before starting."
require_command curl
if [ -n "${APP_ENV_FILE:-}" ]; then
    [[ "$APP_ENV_FILE" = /* ]] || fail "APP_ENV_FILE must be an absolute path."
else
    APP_ENV_FILE="$PROJECT_ROOT/backend/.env"
fi
[ -f "$APP_ENV_FILE" ] || fail "Application environment file not found: $APP_ENV_FILE"
[ ! -L "$APP_ENV_FILE" ] || fail "Application environment file must not be a symlink."
export APP_ENV_FILE
"$PROJECT_ROOT/backend/venv/bin/python" "$SCRIPT_DIR/check_annotations.py" --env-file "$APP_ENV_FILE"
# New frames and working files must not become group/world-readable.
umask 077
[ -s "$PROJECT_ROOT/frontend/dist/index.html" ] || fail "Run deploy/install.sh to build the frontend first."
mkdir -p "$PROJECT_ROOT/logs"
BACKEND_PID_FILE="$PROJECT_ROOT/logs/backend.pid"
FRONTEND_PID_FILE="$PROJECT_ROOT/logs/frontend.pid"
BACKEND_MARKER="$PROJECT_ROOT/backend/venv/bin/python -m uvicorn"
FRONTEND_MARKER="$PROJECT_ROOT/frontend/server.mjs"
if owned_pid "$BACKEND_PID_FILE" "$BACKEND_MARKER" >/dev/null ||
   owned_pid "$FRONTEND_PID_FILE" "$FRONTEND_MARKER" >/dev/null; then
    fail "An instance from this directory is already running; stop it explicitly first."
fi
for file in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
    [ ! -e "$file" ] || fail "PID file exists; inspect it and run deploy/stop.sh first."
done
bash "$SCRIPT_DIR/infra.sh" up
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
    local pid
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null || true
    done
    [ -z "$FRONTEND_PID" ] || wait "$FRONTEND_PID" 2>/dev/null || true
    [ -z "$BACKEND_PID" ] || wait "$BACKEND_PID" 2>/dev/null || true
    rm -f "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$PROJECT_ROOT/backend"
# APP_ENV_FILE, if explicitly supplied by the operator, is read by the application,
# never sourced by this script. Prefer injected environment variables.
nohup "$PROJECT_ROOT/backend/venv/bin/python" -m uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --workers 1 \
    > "$PROJECT_ROOT/logs/backend.log" 2>&1 &
BACKEND_PID=$!
printf '%s\n' "$BACKEND_PID" > "$BACKEND_PID_FILE"

wait_http() {
    local url="$1" pid="$2" attempt
    for attempt in {1..90}; do
        kill -0 "$pid" 2>/dev/null || return 1
        if curl --fail --silent --max-time 2 --noproxy '*' "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}
wait_http http://127.0.0.1:8000/api/system/health "$BACKEND_PID" ||
    fail "Backend liveness failed; inspect logs/backend.log. No cloud readiness is implied."
cd "$PROJECT_ROOT/frontend"
export API_TARGET="http://127.0.0.1:8000"
PORT="${PORT:-3000}"
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] ||
    fail "PORT must be an integer from 1 to 65535."
export PORT
nohup node "$PROJECT_ROOT/frontend/server.mjs" > "$PROJECT_ROOT/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
printf '%s\n' "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
wait_http "http://127.0.0.1:$PORT/" "$FRONTEND_PID" || fail "Frontend failed; inspect logs/frontend.log."
printf 'Application HTTP liveness passed. UI: http://<ECS>:%s\n' "$PORT"
printf 'Local MySQL/Milvus are healthy. TOS and both Ark models must be checked separately.\n'
if [ "$MODE" = "--daemon" ]; then
    trap - EXIT INT TERM
else
    printf 'Logs: logs/backend.log and logs/frontend.log. Ctrl+C stops this instance.\n'
    while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
        sleep 1
    done
    fail "A service exited; inspect the logs."
fi
