#!/bin/bash
# Shared checks; sourcing this file does not load application configuration.

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

check_python() {
    PYTHON_BIN="${PYTHON_BIN:-python3.11}"
    require_command "$PYTHON_BIN"
    "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)' ||
        fail "Python 3.11 is required; set PYTHON_BIN to its executable."
}

check_node() {
    require_command node
    require_command npm
    node -e 'const [a,b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 12) ? 0 : 1)' ||
        fail "Node.js 22.12+ is required for Vite 7 (use a supported LTS release)."
}

check_docker_compose() {
    require_command docker
    docker compose version >/dev/null 2>&1 ||
        fail "Docker Compose V2 is required (the 'docker compose' command)."
}

check_media_tools() {
    local tool
    for tool in ffmpeg ffprobe; do
        require_command "$tool"
        "$tool" -version >/dev/null 2>&1 ||
            fail "$tool is installed but cannot run; install a supported FFmpeg build."
    done
}

check_venv() {
    [ -x "$PROJECT_ROOT/backend/venv/bin/python" ] || fail "Run deploy/install.sh first."
    "$PROJECT_ROOT/backend/venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)' ||
        fail "Existing backend/venv is not Python 3.11; recreate it explicitly."
}

owned_pid() {
    local pid_file="$1" marker="$2" pid command_line
    [ -f "$pid_file" ] || return 1
    IFS= read -r pid < "$pid_file" || return 1
    [[ "$pid" =~ ^[0-9]+$ ]] && [ "$pid" -gt 1 ] || return 1
    command_line="$(ps -p "$pid" -o args= 2>/dev/null)" || return 1
    [[ "$command_line" == *"$marker"* ]] || return 1
    printf '%s\n' "$pid"
}
