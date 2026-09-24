"""Versioned MySQL schema entry point, also callable with an injected SQLite engine.

Run with ``python -m app.models.migrations`` after provisioning the database.
Legacy exports are imported separately: this module never renames legacy tables,
copies credentials, creates databases, or silently accepts incompatible schemas.
"""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import (
    CheckConstraint, Column, DateTime, Index, Integer, MetaData, String, Table, Text, UniqueConstraint,
    inspect, select, text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateIndex, CreateTable

from app.models.database import Base
from app.models.migrations_v1 import metadata as baseline_metadata
from app.models import models  # Register business tables without initializing a client.


class SchemaConflictError(RuntimeError):
    """Only static schema identifiers, never row values or driver messages."""


_version_metadata = MetaData()
schema_versions = Table(
    "schema_versions",
    _version_metadata,
    Column("version", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("applied_at", DateTime, nullable=False),
    mysql_charset="utf8mb4",
    mysql_engine="InnoDB",
)


def _historical_metadata(version: int) -> MetaData:
    """Freeze v2/v3 rebuild targets independently of evolving ORM models."""
    metadata = MetaData()
    for table in baseline_metadata.tables.values():
        table.to_metadata(metadata)
    for name in ("media_files", "media_tags", "import_tasks", "search_history"):
        table = metadata.tables[name]
        table.append_column(Column("user_id", String(36), nullable=True))
        Index(f"ix_{name}_user_id", table.c.user_id)
    metadata.tables["users"].append_column(
        Column("is_demo", Integer, nullable=False, server_default="0")
    )
    media = metadata.tables["media_files"]
    for index in media.indexes:
        if index.name == "ix_media_files_tos_url":
            index.unique = False
    media.append_constraint(
        UniqueConstraint("user_id", "tos_url", name="uq_media_files_user_tos_url")
    )
    if version >= 3:
        tags = metadata.tables["media_tags"]
        tags.append_column(Column("source", String(20), nullable=False, server_default="default"))
        tags.append_constraint(CheckConstraint(
            "source IN ('default', 'custom')", name="ck_media_tags_source",
        ))
        Index(
            "ix_media_tags_user_source_category_tag",
            tags.c.user_id, tags.c.source, tags.c.category, tags.c.tag_name,
        )
        tasks = metadata.tables["import_tasks"]
        tasks.append_column(Column("tag_mode", String(20), nullable=False, server_default="default"))
        tasks.append_column(Column("custom_tag_prompt", Text, nullable=True))
        tasks.append_constraint(CheckConstraint(
            "tag_mode IN ('default', 'custom')", name="ck_import_tasks_tag_mode",
        ))
    return metadata


_v2_metadata = _historical_metadata(2)
_v3_metadata = _historical_metadata(3)


def _validate_table(
    connection: Connection, table: Table, *, validate_indexes: bool = True,
) -> None:
    inspector = inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    if set(columns) != set(table.columns.keys()):
        raise SchemaConflictError(f"Schema column conflict: {table.name}")
    for expected in table.columns:
        actual = columns[expected.name]
        expected_type = expected.type.dialect_impl(connection.dialect)
        if (
            actual["type"]._type_affinity is not expected_type._type_affinity
            or getattr(actual["type"], "length", None) != getattr(expected_type, "length", None)
            or bool(actual["nullable"]) != expected.nullable
        ):
            raise SchemaConflictError(f"Schema type/nullability conflict: {table.name}.{expected.name}")
        if connection.dialect.name == "mysql":
            actual_type = actual["type"].compile(dialect=connection.dialect).split(" COLLATE ")[0]
            target_type = expected_type.compile(dialect=connection.dialect).split(" COLLATE ")[0]
            # MySQL may report INTEGER as INTEGER(11); the affinity check above
            # covers integers, but BIGINT must not silently degrade to INT.
            if ("BIGINT" in actual_type) != ("BIGINT" in target_type):
                raise SchemaConflictError(f"Schema integer width conflict: {table.name}.{expected.name}")
            collation = getattr(expected_type, "collation", None)
            if collation and getattr(actual["type"], "collation", None) != collation:
                raise SchemaConflictError(f"Schema collation conflict: {table.name}.{expected.name}")
    expected_pk = [column.name for column in table.primary_key]
    if inspector.get_pk_constraint(table.name)["constrained_columns"] != expected_pk:
        raise SchemaConflictError(f"Schema primary key conflict: {table.name}")
    indexes = inspector.get_indexes(table.name)
    unique_columns = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)
    } | {tuple(item["column_names"]) for item in indexes if item.get("unique")}
    expected_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    } | {
        tuple(column.name for column in index.columns)
        for index in table.indexes if index.unique
    }
    if not expected_unique.issubset(unique_columns):
        raise SchemaConflictError(f"Schema unique constraint conflict: {table.name}")
    indexed_columns = {tuple(item["column_names"]) for item in indexes} | unique_columns
    for index in table.indexes:
        if validate_indexes and tuple(column.name for column in index.columns) not in indexed_columns:
            raise SchemaConflictError(f"Schema index conflict: {table.name}")
    actual_fks = {
        (
            tuple(item["constrained_columns"]), item["referred_table"],
            tuple(item["referred_columns"]), item.get("options", {}).get("ondelete", "").upper(),
        )
        for item in inspector.get_foreign_keys(table.name)
    }
    if connection.dialect.name == "sqlite":
        # SQLite reflection can omit actions on ALTER-added inline references.
        quote = connection.dialect.identifier_preparer.quote
        grouped = {}
        for row in connection.execute(text(
            f"PRAGMA foreign_key_list({quote(table.name)})"
        )).mappings():
            grouped.setdefault(row["id"], []).append(row)
        actual_fks = {
            (
                tuple(row["from"] for row in sorted(rows, key=lambda row: row["seq"])),
                rows[0]["table"],
                tuple(row["to"] for row in sorted(rows, key=lambda row: row["seq"])),
                rows[0]["on_delete"] if rows[0]["on_delete"] != "NO ACTION" else "",
            )
            for rows in grouped.values()
        }
    for constraint in table.foreign_key_constraints:
        expected_fk = (
            tuple(element.parent.name for element in constraint.elements),
            constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements),
            (constraint.ondelete or "").upper(),
        )
        if expected_fk not in actual_fks:
            raise SchemaConflictError(f"Schema foreign key conflict: {table.name}")


def _baseline(connection: Connection) -> None:
    # MySQL DDL auto-commits. Validate pre-existing tables before doing any work;
    # an interrupted CREATE sequence can then be resumed without data loss.
    existing = set(inspect(connection).get_table_names())
    for table in baseline_metadata.sorted_tables:
        if table.name in existing:
            _validate_table(connection, table)
    baseline_metadata.create_all(connection, checkfirst=True)
    for table in baseline_metadata.sorted_tables:
        _validate_table(connection, table)


def _sqlite_rebuild_v2(connection: Connection) -> None:
    """SQLite test migration equivalent to the production ALTER statements."""
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    for name in ("media_files", "media_tags", "import_tasks", "search_history", "users"):
        target = _v2_metadata.tables[name]
        temporary_name = f"__schema_v2_{name}"
        temporary = target.to_metadata(MetaData(), name=temporary_name)
        connection.execute(CreateTable(temporary))
        existing_columns = {column["name"] for column in inspector.get_columns(name)}
        target_columns = [column.name for column in target.columns]
        select_values = [
            quote(column) if column in existing_columns
            else "0" if column == "is_demo"
            else "NULL"
            for column in target_columns
        ]
        connection.execute(text(
            f"INSERT INTO {quote(temporary_name)} "
            f"({', '.join(quote(column) for column in target_columns)}) "
            f"SELECT {', '.join(select_values)} FROM {quote(name)}"
        ))
        connection.execute(text(f"DROP TABLE {quote(name)}"))
        connection.execute(text(
            f"ALTER TABLE {quote(temporary_name)} RENAME TO {quote(name)}"
        ))
        for index in target.indexes:
            connection.execute(CreateIndex(index))


def _mysql_upgrade_v2(connection: Connection) -> None:
    quote = connection.dialect.identifier_preparer.quote
    for table_name in ("media_files", "media_tags", "import_tasks", "search_history"):
        connection.execute(text(
            f"ALTER TABLE {quote(table_name)} "
            f"ADD COLUMN {quote('user_id')} VARCHAR(36) NULL"
        ))
    connection.execute(text(
        f"ALTER TABLE {quote('users')} "
        f"ADD COLUMN {quote('is_demo')} INTEGER NOT NULL DEFAULT 0"
    ))

    media_indexes = inspect(connection).get_indexes("media_files")
    legacy_unique = next(
        (
            index["name"] for index in media_indexes
            if index.get("unique") and index.get("column_names") == ["tos_url"]
        ),
        None,
    )
    if legacy_unique:
        connection.execute(text(
            f"ALTER TABLE {quote('media_files')} DROP INDEX {quote(legacy_unique)}"
        ))

    statements = (
        "CREATE INDEX ix_media_files_user_id ON media_files (user_id)",
        "CREATE INDEX ix_media_files_tos_url ON media_files (tos_url)",
        "ALTER TABLE media_files ADD CONSTRAINT uq_media_files_user_tos_url UNIQUE (user_id, tos_url)",
        "CREATE INDEX ix_media_tags_user_id ON media_tags (user_id)",
        "CREATE INDEX ix_import_tasks_user_id ON import_tasks (user_id)",
        "CREATE INDEX ix_search_history_user_id ON search_history (user_id)",
    )
    for statement in statements:
        connection.execute(text(statement))


def _user_isolation_v2(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        _sqlite_rebuild_v2(connection)
    elif connection.dialect.name == "mysql":
        _mysql_upgrade_v2(connection)
    else:
        raise SchemaConflictError("Unsupported migration dialect")


def _sqlite_upgrade_v3(connection: Connection) -> None:
    """Rebuild changed tables so SQLite receives constraints and indexes."""
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    fallback_values = {
        "source": "'default'",
        "tag_mode": "'default'",
        "custom_tag_prompt": "NULL",
    }
    for name in ("media_tags", "import_tasks"):
        target = _v3_metadata.tables[name]
        temporary_name = f"__schema_v3_{name}"
        temporary = target.to_metadata(MetaData(), name=temporary_name)
        connection.execute(CreateTable(temporary))
        existing_columns = {column["name"] for column in inspector.get_columns(name)}
        target_columns = [column.name for column in target.columns]
        select_values = [
            quote(column) if column in existing_columns
            else fallback_values[column]
            for column in target_columns
        ]
        connection.execute(text(
            f"INSERT INTO {quote(temporary_name)} "
            f"({', '.join(quote(column) for column in target_columns)}) "
            f"SELECT {', '.join(select_values)} FROM {quote(name)}"
        ))
        connection.execute(text(f"DROP TABLE {quote(name)}"))
        connection.execute(text(
            f"ALTER TABLE {quote(temporary_name)} RENAME TO {quote(name)}"
        ))
        for index in target.indexes:
            connection.execute(CreateIndex(index))


def _mysql_upgrade_v3(connection: Connection) -> None:
    statements = (
        "ALTER TABLE media_tags "
        "ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'default'",
        "ALTER TABLE media_tags "
        "ADD CONSTRAINT ck_media_tags_source "
        "CHECK (source IN ('default', 'custom'))",
        "CREATE INDEX ix_media_tags_user_source_category_tag "
        "ON media_tags (user_id, source, category, tag_name)",
        "ALTER TABLE import_tasks "
        "ADD COLUMN tag_mode VARCHAR(20) NOT NULL DEFAULT 'default', "
        "ADD COLUMN custom_tag_prompt TEXT NULL",
        "ALTER TABLE import_tasks "
        "ADD CONSTRAINT ck_import_tasks_tag_mode "
        "CHECK (tag_mode IN ('default', 'custom'))",
    )
    for statement in statements:
        connection.execute(text(statement))


def _tag_taxonomy_v3(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        _sqlite_upgrade_v3(connection)
    elif connection.dialect.name == "mysql":
        _mysql_upgrade_v3(connection)
    else:
        raise SchemaConflictError("Unsupported migration dialect")


def _multimodal_annotations_v4(connection: Connection) -> None:
    """Additive and resumable after MySQL's auto-committed DDL; never copy rows."""
    if connection.dialect.name not in {"sqlite", "mysql"}:
        raise SchemaConflictError("Unsupported migration dialect")
    quote = connection.dialect.identifier_preparer.quote
    for name in ("media_files", "import_tasks"):
        target = Base.metadata.tables[name]
        existing = {column["name"] for column in inspect(connection).get_columns(name)}
        historical = set(_v3_metadata.tables[name].columns.keys())
        for column in target.columns:
            if column.name in historical or column.name in existing:
                continue
            definition = str(CreateColumn(column).compile(dialect=connection.dialect))
            if column.name == "published_annotation_run_id" and connection.dialect.name == "sqlite":
                definition += " REFERENCES annotation_runs (id) ON DELETE SET NULL"
            connection.execute(text(
                f"ALTER TABLE {quote(name)} ADD COLUMN {definition}"
            ))
        existing_indexes = {index["name"] for index in inspect(connection).get_indexes(name)}
        for index in target.indexes:
            if index.name not in existing_indexes:
                connection.execute(CreateIndex(index))

    new_tables = [
        models.AnnotationRun.__table__, models.AnnotationFrame.__table__,
        models.AnnotationResultSet.__table__, models.AnnotationResultSetMember.__table__,
    ]
    # Validate resumed tables, rather than adopting a same-named incompatible table.
    existing = set(inspect(connection).get_table_names())
    for table in new_tables:
        if table.name in existing:
            _validate_table(connection, table, validate_indexes=False)
            indexes = {index["name"] for index in inspect(connection).get_indexes(table.name)}
            for index in table.indexes:
                if index.name not in indexes:
                    connection.execute(CreateIndex(index))
            _validate_table(connection, table)
    Base.metadata.create_all(connection, tables=new_tables, checkfirst=True)
    if connection.dialect.name == "mysql":
        pointer = next(
            constraint for constraint in models.MediaFile.__table__.foreign_key_constraints
            if constraint.name == "fk_media_published_annotation_run"
        )
        foreign_keys = inspect(connection).get_foreign_keys("media_files")
        if not any(item["name"] == pointer.name for item in foreign_keys):
            connection.execute(AddConstraint(pointer))


MIGRATIONS = (
    (1, "rds_mysql8_baseline", _baseline),
    (2, "user_data_isolation", _user_isolation_v2),
    (3, "tag_taxonomy_sources", _tag_taxonomy_v3),
    (4, "multimodal_annotations", _multimodal_annotations_v4),
)


def apply_migrations(connection: Connection) -> None:
    """Apply ordered versions. Caller owns the transaction and migration lock."""
    existing = set(inspect(connection).get_table_names())
    if schema_versions.name in existing:
        _validate_table(connection, schema_versions)
        applied = connection.execute(
            select(schema_versions.c.version, schema_versions.c.name).order_by(schema_versions.c.version)
        ).all()
    else:
        applied = []
    expected = [(version, name) for version, name, _ in MIGRATIONS]
    if [tuple(row) for row in applied] != expected[:len(applied)]:
        raise SchemaConflictError("Schema migration history conflict")
    if applied:
        required = Base.metadata if len(applied) == len(MIGRATIONS) else baseline_metadata
        missing = set(required.tables) - existing
        if missing:
            raise SchemaConflictError("Versioned schema is missing business tables")
    for version, name, upgrade in MIGRATIONS[len(applied):]:
        upgrade(connection)
        schema_versions.create(connection, checkfirst=True)
        connection.execute(schema_versions.insert().values(
            version=version, name=name,
            applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
    # Verify even when there are no pending migrations.
    for table in Base.metadata.sorted_tables:
        _validate_table(connection, table)


async def migrate(engine: AsyncEngine) -> None:
    """Serialize MySQL initializers, keeping the lock until the version commits."""
    lock_name = "schema:" + sha256((engine.url.database or "").encode()).hexdigest()[:48]
    async with engine.connect() as connection:
        locked = False
        try:
            if connection.dialect.name == "mysql":
                locked = await connection.scalar(
                    text("SELECT GET_LOCK(:name, 30)"), {"name": lock_name}
                ) == 1
                if not locked:
                    raise SchemaConflictError("Schema migration lock unavailable")
            await connection.run_sync(apply_migrations)
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise
        finally:
            if locked:
                await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                await connection.commit()


async def _main() -> None:
    from app.models.database import close_db, init_db

    try:
        await init_db()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(_main())
