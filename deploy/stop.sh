#!/bin/bash
# Stop only PID-file-owned processes from this project directory.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
[ "$#" -eq 0 ] || fail "Usage: deploy/stop.sh"

stop_service() {
    local file="$1" marker="$2" pid attempt
    if pid="$(owned_pid "$file" "$marker")"; then
        kill "$pid" 2>/dev/null || true
        for attempt in {1..30}; do
            if ! owned_pid "$file" "$marker" >/dev/null; then
                rm -f "$file"
                printf 'Stopped PID %s.\n' "$pid"
                return
            fi
            sleep 1
        done
        fail "PID $pid still exists; inspect it before any forced termination."
    elif [ -f "$file" ]; then
        fail "Unverifiable/stale PID file: $file. Inspect the process and remove the file manually if safe."
    else
        printf 'No managed PID file: %s\n' "$file"
    fi
}

stop_service "$PROJECT_ROOT/logs/frontend.pid" "$PROJECT_ROOT/frontend/server.mjs"
stop_service "$PROJECT_ROOT/logs/backend.pid" "$PROJECT_ROOT/backend/venv/bin/python -m uvicorn"
printf 'Application stop finished. Local infrastructure is still running.\n'
printf 'To stop containers without deleting data, run: bash deploy/infra.sh down\n'
