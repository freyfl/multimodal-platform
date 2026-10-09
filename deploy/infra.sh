#!/bin/bash
# Manage server-local MySQL and Milvus. Normal shutdown always retains volumes.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"

[ "$#" -ge 1 ] && [ "$#" -le 2 ] ||
    fail "Usage: deploy/infra.sh {up|down|wait|status|logs} [service]"
ACTION="$1"
SERVICE="${2:-}"
case "$ACTION" in
    up|down|wait|status) [ -z "$SERVICE" ] ||
        fail "Usage: deploy/infra.sh $ACTION" ;;
    logs) ;;
    *) fail "Usage: deploy/infra.sh {up|down|wait|status|logs} [service]" ;;
esac

require_command docker
docker compose version >/dev/null 2>&1 ||
    fail "Docker Compose V2 is required (the 'docker compose' command)."
docker info >/dev/null 2>&1 || fail "Docker daemon is not available."

if [ -n "${APP_ENV_FILE:-}" ]; then
    [[ "$APP_ENV_FILE" = /* ]] || fail "APP_ENV_FILE must be an absolute path."
    ENV_FILE="$APP_ENV_FILE"
else
    ENV_FILE="$PROJECT_ROOT/backend/.env"
fi
[ -f "$ENV_FILE" ] || fail "Infrastructure environment file not found: $ENV_FILE"
[ ! -L "$ENV_FILE" ] || fail "Infrastructure environment file must not be a symlink."
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.infrastructure.yml"
[ -f "$COMPOSE_FILE" ] || fail "Missing infrastructure Compose file."

compose() {
    docker compose \
        --project-directory "$PROJECT_ROOT" \
        --env-file "$ENV_FILE" \
        -f "$COMPOSE_FILE" "$@"
}

case "$ACTION" in
    up)
        compose config --quiet
        compose up -d --wait
        printf 'Local MySQL and Milvus infrastructure is healthy; persistent volumes retained.\n'
        ;;
    down)
        compose down
        printf 'Infrastructure stopped; persistent volumes were not removed.\n'
        ;;
    wait)
        compose up -d --wait
        ;;
    status)
        compose ps
        ;;
    logs)
        if [ -n "$SERVICE" ]; then
            compose logs --tail=200 "$SERVICE"
        else
            compose logs --tail=200
        fi
        ;;
esac
