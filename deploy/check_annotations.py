#!/usr/bin/env python3
"""Read-only deployment preflight; no app imports, writes, or network requests."""

import argparse
import math
import os
from pathlib import Path
import stat
import sys

from dotenv import dotenv_values


# Names shared with the deployment template; runtime enforcement belongs to T3.
INTEGER_LIMITS = {
    "ANNOTATION_MAX_VIDEO_BYTES": (1, None),
    "ANNOTATION_MAX_VIDEO_SECONDS": (1, None),
    "ANNOTATION_MAX_FRAME_PIXELS": (1, None),
    "ANNOTATION_DECODE_CONCURRENCY": (1, None),
    "ANNOTATION_DECODE_TIMEOUT": (1, None),
}


def contains(parent, child):
    return parent == child or parent in child.parents


def validate_config(values, project_root, *, check_filesystem=True):
    """Return field-only errors, never credentials or configured path values."""
    errors = []
    for name, (minimum, maximum) in INTEGER_LIMITS.items():
        raw = values.get(name) or ""
        if not raw.isascii() or not raw.isdecimal():
            errors.append(f"{name}: explicit positive integer required")
            continue
        value = int(raw)
        if value < minimum or (maximum is not None and value > maximum):
            errors.append(f"{name}: outside supported range")

    for name, minimum in (("TASK_TIMEOUT", 7200), ("ARK_REQUEST_TIMEOUT", 300)):
        try:
            value = float(values.get(name) or "")
        except (TypeError, ValueError):
            value = math.nan
        if not math.isfinite(value) or value < minimum:
            errors.append(f"{name}: explicitly configure at least {minimum} seconds")
    if values.get("MILVUS_COLLECTION") != "media_vectors_v2":
        errors.append("MILVUS_COLLECTION: annotation upgrades must retain media_vectors_v2")

    paths = {}
    root = project_root.resolve()
    for name in ("ANNOTATION_STORAGE_DIR", "ANNOTATION_TEMP_DIR"):
        raw = values.get(name) or ""
        path = Path(raw)
        if not raw or not path.is_absolute():
            errors.append(f"{name}: explicit absolute path required")
            continue
        try:
            resolved = path.resolve()
            if contains(root, resolved) or contains(resolved, root):
                errors.append(f"{name}: must be outside and not contain the release directory")
            if check_filesystem and any(part.is_symlink() for part in (path, *path.parents)):
                errors.append(f"{name}: symlinked paths are not allowed")
            paths[name] = resolved
            if not check_filesystem:
                continue
            info = path.stat()
            if not stat.S_ISDIR(info.st_mode):
                errors.append(f"{name}: provision a directory before starting")
            elif (info.st_uid != os.geteuid()
                  or stat.S_IMODE(info.st_mode) != 0o700
                  or not os.access(path, os.R_OK | os.W_OK | os.X_OK)):
                errors.append(f"{name}: requires application ownership and mode 0700")
        except (OSError, RuntimeError, ValueError):
            errors.append(f"{name}: directory missing or inaccessible")
    if len(paths) == 2:
        storage, temporary = paths.values()
        if contains(storage, temporary) or contains(temporary, storage):
            errors.append("ANNOTATION_TEMP_DIR: must be disjoint from ANNOTATION_STORAGE_DIR")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    path = args.env_file
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        parser.exit(1, "ERROR: --env-file must be an existing absolute non-symlink file\n")
    try:
        # No shell evaluation or interpolation; process environment takes precedence.
        values = {**dotenv_values(path, interpolate=False), **os.environ}
        errors = validate_config(values, Path(__file__).resolve().parent.parent)
    except (OSError, UnicodeError, ValueError):
        parser.exit(1, "ERROR: deployment configuration cannot be parsed\n")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Annotation configuration and directory preflight passed (read-only).")
    print("Mount persistence, static-server isolation and runtime limits still require verification.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
