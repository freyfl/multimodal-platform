#!/usr/bin/env python3
"""Release allowlist. Listing inspects names and metadata, never file contents."""

import argparse
import os
from pathlib import Path
import re
import stat
import sys


EXACT_FILES = {
    "README.md", "DEPLOYMENT.md",
    "backend/requirements.txt", "backend/.env.example",
    "frontend/package.json", "frontend/package-lock.json",
    "frontend/index.html", "frontend/server.mjs", "frontend/vite.config.ts",
    "frontend/tsconfig.json", "frontend/tsconfig.node.json",
    "frontend/tsconfig.app.json", "frontend/vite-env.d.ts",
    "frontend/components.d.ts",
}
WEB_SUFFIXES = {".vue", ".ts", ".js", ".mjs", ".css", ".less", ".scss",
                ".html", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp",
                ".ico", ".woff", ".woff2", ".ttf", ".otf"}
TREES = {
    "backend/app": {".py"},
    "backend/scripts": {".py"},
    "frontend/src": WEB_SUFFIXES,
    "frontend/public": WEB_SUFFIXES,
    "frontend/dist": WEB_SUFFIXES,
    "deploy": {".sh", ".py", ".md", ".yml", ".yaml"},
    "docs": {".md", ".html", ".css", ".woff", ".woff2", ".txt"},
}
BLOCKED_PARTS = {
    "node_modules", "venv", "__pycache__", "data", "logs", "exports",
    "export", "dumps", "dump", "backups", "backup", "migration_data",
    "migration-data", "migration_exports", "migration-exports",
    "credentials", "secrets", "certs", "certificates", "fixtures",
    "toolchain", "tools", "superpowers",
}
SENSITIVE_NAME = re.compile(
    r"(^|[._-])(secret|secrets|credential|credentials|private|token|password|"
    r"backup|migration[-_]data|migration[-_]export)([._-]|$)",
    re.IGNORECASE,
)


def safe_path(relative):
    if relative.as_posix() == "backend/.env.example":
        return True
    for part in relative.parts:
        if part.startswith(".") or part.lower() in BLOCKED_PARTS:
            return False
        if any(ord(char) < 32 for char in part) or "\\" in part:
            return False
    name = relative.name.lower()
    if name.startswith(("id_rsa", "id_ed25519", "id_ecdsa")):
        return False
    return not SENSITIVE_NAME.search(name)


def path_has_symlink(root, relative):
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def regular_file(root, relative):
    if path_has_symlink(root, relative):
        return False
    current = root / relative
    try:
        info = current.stat()
        # Reject hardlinks too: an innocuous filename must not alias a secret.
        return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    except FileNotFoundError:
        return False


def collect(root):
    root = root.resolve()
    files = set()
    for name in EXACT_FILES:
        relative = Path(name)
        if safe_path(relative) and regular_file(root, relative):
            files.add(name)
    for directory, suffixes in TREES.items():
        base = root / directory
        if not base.is_dir() or path_has_symlink(root, Path(directory)):
            continue
        for parent, directories, names in os.walk(base, followlinks=False):
            directories[:] = sorted(
                name for name in directories
                if safe_path((Path(parent) / name).relative_to(root))
                and not (Path(parent) / name).is_symlink()
            )
            for name in names:
                relative = (Path(parent) / name).relative_to(root)
                if (relative.suffix.lower() in suffixes and safe_path(relative)
                        and regular_file(root, relative)):
                    files.add(relative.as_posix())
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--null", action="store_true", help="NUL-delimited tar input")
    parser.add_argument("--prefix", default="", help="Archive top-level directory")
    args = parser.parse_args()
    if args.prefix and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.prefix):
        parser.error("Unsafe archive prefix")
    for name in collect(args.root.resolve()):
        name = f"{args.prefix}/{name}" if args.prefix else name
        sys.stdout.buffer.write(name.encode("utf-8") + (b"\0" if args.null else b"\n"))


if __name__ == "__main__":
    main()
