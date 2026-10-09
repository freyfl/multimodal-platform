"""Import a versioned legacy JSON export into MySQL.

Dry-run is the default. The source is read once and never modified. All
validation completes before the single apply transaction starts.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.models.models import (
    ImportTask,
    LoginLog,
    MediaFile,
    MediaTag,
    SearchHistory,
    User,
    UserSession,
    UserSystemSettings,
)
from app.utils.helpers import build_tos_url, parse_tos_url


FORMAT_VERSION = 1
TABLES = {
    "users": User,
    "media_files": MediaFile,
    "media_tags": MediaTag,
    "import_tasks": ImportTask,
    "search_history": SearchHistory,
    "login_logs": LoginLog,
    "user_sessions": UserSession,
    "user_system_settings": UserSystemSettings,
}
INSERT_ORDER = (
    "users",
    "media_files",
    "import_tasks",
    "search_history",
    "login_logs",
    "user_sessions",
    "user_system_settings",
    "media_tags",
)
ALIASES = {
    "media_files": {"oss_url": "tos_url"},
    "import_tasks": {"oss_directory": "tos_directory"},
}
IGNORED_FIELDS = {
    "media_files": {
        "embedding",
        "embedding_model",
        "embedding_dimension",
        "vector_model",
        "vector_dimension",
        "vector_instruction_version",
        "vector_collection",
        "vector_id",
    },
    "user_system_settings": {
        "oss_access_key_id",
        "oss_access_key_secret",
        "oss_security_token",
        "oss_bucket_name",
        "oss_endpoint",
        "oss_region",
        "oss_custom_domain",
        "dashscope_api_key",
        "api_key",
        "embedding_model",
        "embedding_dimension",
        "tag_model",
    },
}
UNIQUE_FIELDS = {
    "users": (("username",), ("email",)),
    "media_files": (("user_id", "tos_url"),),
    "import_tasks": (("task_id",),),
    "user_sessions": (("refresh_token",),),
    "user_system_settings": (("user_id",),),
}
RELATIONS = (
    ("media_tags", "media_id", "media_files"),
    ("login_logs", "user_id", "users"),
    ("user_sessions", "user_id", "users"),
    ("user_system_settings", "user_id", "users"),
)


class MigrationInputError(ValueError):
    """The report contains locations and categories, never source values."""

    def __init__(self, report: dict[str, Any]):
        super().__init__("legacy export validation failed")
        self.report = report


@dataclass(frozen=True)
class StorageMapping:
    source_bucket: str
    source_prefix: str
    target_bucket: str
    target_prefix: str

    @classmethod
    def parse(cls, value: str) -> "StorageMapping":
        try:
            source, target = value.split("=", 1)
            source_bucket, source_prefix = _storage_parts(source, "oss")
            target_bucket, target_prefix = _storage_parts(target, "tos")
            build_tos_url(target_bucket, target_prefix)
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError(
                "mapping must be oss://bucket/prefix=tos://bucket/prefix"
            ) from None
        return cls(source_bucket, source_prefix, target_bucket, target_prefix)

    def matches(self, bucket: str, key: str) -> bool:
        return bucket == self.source_bucket and (
            not self.source_prefix
            or key == self.source_prefix
            or key.startswith(self.source_prefix + "/")
        )

    def convert(self, bucket: str, key: str) -> str:
        suffix = key[len(self.source_prefix):].lstrip("/")
        target_key = "/".join(part for part in (self.target_prefix, suffix) if part)
        return build_tos_url(self.target_bucket, target_key)


def _storage_parts(value: str, scheme: str) -> tuple[str, str]:
    parsed = urlsplit(value, allow_fragments=False)
    if parsed.scheme != scheme or not parsed.netloc or parsed.query:
        raise ValueError
    try:
        path = unquote(parsed.path.lstrip("/"), encoding="utf-8", errors="strict").rstrip("/")
    except UnicodeError:
        raise ValueError from None
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError
    return parsed.netloc, path


def map_storage_uri(value: str, mappings: Iterable[StorageMapping]) -> str:
    bucket, key = _storage_parts(value, "oss")
    candidates = [mapping for mapping in mappings if mapping.matches(bucket, key)]
    if not candidates:
        raise ValueError("missing_mapping")
    longest = max(len(mapping.source_prefix) for mapping in candidates)
    best = [mapping for mapping in candidates if len(mapping.source_prefix) == longest]
    if len(best) != 1:
        raise ValueError("ambiguous_mapping")
    return best[0].convert(bucket, key)


def load_export(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise MigrationInputError(_report(["source:invalid_json"])) from None
    if (
        not isinstance(payload, dict)
        or payload.get("format_version") != FORMAT_VERSION
        or not isinstance(payload.get("tables"), dict)
    ):
        raise MigrationInputError(_report(["source:invalid_format"]))
    return payload


def _report(errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "valid": not errors,
        "mode": "dry-run",
        "inserted": {name: 0 for name in TABLES},
        "already_present": {name: 0 for name in TABLES},
        "ignored_legacy_fields": 0,
        "errors": errors or [],
    }


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _normalize_row(
    table_name: str,
    index: int,
    source: Any,
    mappings: list[StorageMapping],
    report: dict[str, Any],
) -> dict[str, Any] | None:
    location = f"{table_name}[{index}]"
    if not isinstance(source, dict):
        report["errors"].append(f"{location}:not_object")
        return None
    model = TABLES[table_name]
    aliases = ALIASES.get(table_name, {})
    ignored = IGNORED_FIELDS.get(table_name, set())
    allowed = set(model.__table__.columns.keys())
    row: dict[str, Any] = {}
    for source_name, value in source.items():
        if source_name in ignored:
            report["ignored_legacy_fields"] += 1
            continue
        name = aliases.get(source_name, source_name)
        if name not in allowed or name in row:
            report["errors"].append(f"{location}.{source_name}:unknown_or_duplicate_field")
            continue
        row[name] = value
    if not isinstance(row.get("id"), str) or not row["id"]:
        report["errors"].append(f"{location}.id:required")
    for column in model.__table__.columns:
        if column.name not in row:
            if not column.nullable and column.default is None and not column.autoincrement:
                report["errors"].append(f"{location}.{column.name}:required")
            continue
        value = row[column.name]
        try:
            python_type = column.type.python_type
            if value is None:
                if not column.nullable:
                    raise ValueError
            elif python_type is datetime:
                row[column.name] = _coerce_datetime(value)
            elif python_type is int:
                if type(value) is not int:
                    raise ValueError
            elif python_type is float:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError
                row[column.name] = float(value)
            elif python_type is str:
                if not isinstance(value, str):
                    raise ValueError
                length = getattr(column.type, "length", None)
                if length and len(value) > length:
                    raise ValueError
        except (AttributeError, TypeError, ValueError):
            report["errors"].append(f"{location}.{column.name}:invalid_value")
    try:
        if table_name == "media_files" and isinstance(row.get("tos_url"), str):
            row["tos_url"] = map_storage_uri(row["tos_url"], mappings)
        elif table_name == "import_tasks" and isinstance(row.get("tos_directory"), str):
            row["tos_directory"] = map_storage_uri(row["tos_directory"], mappings)
    except ValueError as error:
        report["errors"].append(f"{location}:storage_{error}")
    if table_name == "media_files":
        parsed = parse_tos_url(row.get("tos_url"))
        if parsed is None or not parsed["path"]:
            report["errors"].append(f"{location}.tos_url:invalid_object_uri")
        if row.get("file_type") not in ("image", "video"):
            report["errors"].append(f"{location}.file_type:invalid_value")
        row.update(
            vector_status="pending",
            vector_id=None,
            vector_model=None,
            vector_dimension=None,
            vector_instruction_version=None,
            vector_collection=None,
        )
    elif table_name == "user_system_settings":
        # Keep the row identity and history association, but never translate
        # credentials or old model choices into a new cloud security context.
        row.update(
            tos_access_key_id=None,
            tos_access_key_secret=None,
            tos_security_token=None,
            tos_bucket_name=None,
            tos_endpoint=None,
            tos_region=None,
            tos_custom_domain=None,
            ark_api_key=None,
            embedding_model=None,
            embedding_dimension=None,
            tag_model=None,
        )
    return row


def normalize_export(
    payload: dict[str, Any], mappings: list[StorageMapping]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    report = _report()
    tables = payload["tables"]
    unknown_tables = set(tables) - set(TABLES)
    missing_tables = set(TABLES) - set(tables)
    for name in sorted(unknown_tables):
        report["errors"].append(f"tables.{name}:unknown_table")
    for name in sorted(missing_tables):
        report["errors"].append(f"tables.{name}:required")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for table_name in TABLES:
        records = tables.get(table_name, [])
        if not isinstance(records, list):
            report["errors"].append(f"tables.{table_name}:not_array")
            normalized[table_name] = []
            continue
        normalized[table_name] = [
            row
            for index, source in enumerate(records)
            if (row := _normalize_row(table_name, index, source, mappings, report)) is not None
        ]
    _validate_source_keys(normalized, report)
    report["valid"] = not report["errors"]
    return normalized, report


def _unique_key(table_name: str, fields: tuple[str, ...], values) -> tuple[Any, ...]:
    key = tuple(values(field) for field in fields)
    if table_name == "users":
        key = tuple(value.casefold() if isinstance(value, str) else value for value in key)
    return key


def _validate_source_keys(rows: dict[str, list[dict[str, Any]]], report: dict[str, Any]) -> None:
    for table_name, records in rows.items():
        key_sets = [(("id",), set())]
        key_sets.extend((fields, set()) for fields in UNIQUE_FIELDS.get(table_name, ()))
        for index, row in enumerate(records):
            for fields, seen in key_sets:
                value = _unique_key(table_name, fields, row.get)
                if any(part is None for part in value):
                    continue
                if value in seen:
                    label = "_".join(fields)
                    report["errors"].append(f"{table_name}[{index}]:duplicate_{label}")
                seen.add(value)


def _validate_relations(
    rows: dict[str, list[dict[str, Any]]],
    target_media_ids: set[str],
    target_user_ids: set[str],
    report: dict[str, Any],
) -> None:
    parents = {
        "media_files": target_media_ids | {row.get("id") for row in rows["media_files"]},
        "users": target_user_ids | {row.get("id") for row in rows["users"]},
    }
    for child, field, parent in RELATIONS:
        for index, row in enumerate(rows[child]):
            if row.get(field) not in parents[parent]:
                report["errors"].append(f"{child}[{index}].{field}:missing_relation")


def _comparable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return value


def validate_target(
    session: Session,
    rows: dict[str, list[dict[str, Any]]],
    report: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    existing = {
        table_name: list(session.scalars(select(model)))
        for table_name, model in TABLES.items()
    }
    _validate_relations(
        rows,
        {row.id for row in existing["media_files"]},
        {row.id for row in existing["users"]},
        report,
    )
    pending: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
    for table_name, incoming in rows.items():
        by_id = {row.id: row for row in existing[table_name]}
        unique_maps = [
            (fields, {
                _unique_key(
                    table_name,
                    fields,
                    lambda field, existing_row=row: getattr(existing_row, field),
                ): row.id
                for row in existing[table_name]
                if all(getattr(row, field) is not None for field in fields)
            })
            for fields in UNIQUE_FIELDS.get(table_name, ())
        ]
        for index, values in enumerate(incoming):
            current = by_id.get(values.get("id"))
            if current is not None:
                if all(
                    _comparable(getattr(current, field)) == _comparable(value)
                    for field, value in values.items()
                ):
                    report["already_present"][table_name] += 1
                else:
                    report["errors"].append(f"{table_name}[{index}]:target_primary_key_conflict")
                continue
            conflict = False
            for fields, known in unique_maps:
                key = _unique_key(table_name, fields, values.get)
                if not any(part is None for part in key) and key in known:
                    report["errors"].append(
                        f"{table_name}[{index}]:target_{'_'.join(fields)}_conflict"
                    )
                    conflict = True
            if not conflict:
                pending[table_name].append(values)
    report["valid"] = not report["errors"]
    return pending


def migrate(
    session: Session,
    payload: dict[str, Any],
    mappings: list[StorageMapping],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    rows, report = normalize_export(payload, mappings)
    if report["errors"]:
        raise MigrationInputError(report)
    pending = validate_target(session, rows, report)
    if report["errors"]:
        raise MigrationInputError(report)
    report["planned"] = {name: len(pending[name]) for name in TABLES}
    if not apply:
        return report
    try:
        for table_name in INSERT_ORDER:
            model = TABLES[table_name]
            session.add_all(model(**row) for row in pending[table_name])
        session.flush()
        for table_name in TABLES:
            report["inserted"][table_name] = len(pending[table_name])
        session.commit()
    except BaseException:
        session.rollback()
        raise
    report["mode"] = "apply"
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import legacy metadata JSON into MySQL")
    parser.add_argument("source", type=Path, help="read-only legacy export JSON")
    parser.add_argument(
        "--map",
        dest="mappings",
        type=StorageMapping.parse,
        action="append",
        required=True,
        help="repeatable oss://bucket/prefix=tos://bucket/prefix mapping",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit inserts; omitted means validation-only dry-run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings.require_config("mysql")
        payload = load_export(args.source)
        engine = create_engine(
            settings.mysql_sync_url,
            echo=False,
            hide_parameters=True,
            pool_pre_ping=True,
        )
        try:
            with Session(engine) as session:
                report = migrate(session, payload, args.mappings, apply=args.apply)
        finally:
            engine.dispose()
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    except MigrationInputError as error:
        print(json.dumps(error.report, ensure_ascii=True, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"valid": False, "errors": ["migration:failed"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
