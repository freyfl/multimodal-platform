#!/bin/bash
# Usage: bash deploy/pack.sh [suffix | --list]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
[ "$#" -le 1 ] || fail "Usage: deploy/pack.sh [suffix | --list]"

# Static mode deliberately needs neither Node nor Python 3.11 nor cloud config.
if [ "${1:-}" = "--list" ]; then
    require_command "${PYTHON_BIN:-python3}"
    printf 'Static candidate list only; existing dist is NOT a verified fresh build.\n' >&2
    exec "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/release_manifest.py"
fi
SUFFIX="${1:-}"
[[ "$SUFFIX" =~ ^[A-Za-z0-9._-]*$ ]] || fail "Suffix may contain only letters, digits, dots, underscores and hyphens."
[[ "$SUFFIX" != -* ]] || fail "Unknown option: $SUFFIX"
check_python
check_node
require_command tar
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
[[ "$PROJECT_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail "Unsafe project directory name."
[ -f "$PROJECT_ROOT/backend/.env.example" ] || fail "Missing backend/.env.example."
bash "$SCRIPT_DIR/build.sh"

ARCHIVE="$PROJECT_ROOT/${PROJECT_NAME}-$(date +%Y%m%d)${SUFFIX:+-$SUFFIX}.tar.gz"
[ ! -e "$ARCHIVE" ] && [ ! -L "$ARCHIVE" ] || fail "Archive exists; choose a new suffix."
WORK="$(mktemp -d "$PROJECT_ROOT/.release.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
"$PYTHON_BIN" "$SCRIPT_DIR/release_manifest.py" --null --prefix "$PROJECT_NAME" > "$WORK/files"
export COPYFILE_DISABLE=1
TAR_OPTIONS=()
if tar --no-xattrs -cf /dev/null -T /dev/null 2>/dev/null; then
    TAR_OPTIONS+=(--no-xattrs)
fi
tar "${TAR_OPTIONS[@]}" --no-recursion -czf "$WORK/release.tar.gz" \
    -C "$(dirname "$PROJECT_ROOT")" --null -T "$WORK/files"
tar -tzf "$WORK/release.tar.gz" > "$WORK/archive-files.txt"
mv "$WORK/release.tar.gz" "$ARCHIVE"
printf 'Release created: %s\n' "$ARCHIVE"
printf 'Only allowlisted files included; backend/.env.example is the only environment template.\n'
printf 'Cloud resources and credentials are NOT included or verified.\n'
