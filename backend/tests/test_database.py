"""Offline MySQL contract tests; never require a provisioned database."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import Settings
from app.errors import MissingConfigurationError, ServiceError
from app.models import database
from app.models.database import Base
from app.models.migrations import (
    SchemaConflictError, _mysql_upgrade_v3, _sqlite_upgrade_v3,
    apply_migrations, schema_versions,
)
from app.models.migrations_v1 import metadata as baseline_metadata
from app.models.models import ImportTask, MediaFile, MediaTag, User, UserSystemSettings


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def initialize(engine):
    with engine.begin() as connection:
        apply_migrations(connection)


def test_import_has_no_engine_network_or_dotenv():
    backend = str(Path(__file__).resolve().parents[1])
    script = """
import socket
import dotenv
import sqlalchemy.ext.asyncio
def forbidden(*args, **kwargs):
    raise AssertionError("Import must not create clients or read dotenv")
socket.create_connection = forbidden
socket.socket.connect = forbidden
dotenv.dotenv_values = forbidden
sqlalchemy.ext.asyncio.create_async_engine = forbidden
import app.models.database as db
import app.models.models
assert db._engine is None
assert db._session_factory is None
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": backend, "APP_ENV_FILE": ""},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_empty_configuration_is_lazy(monkeypatch):
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(database, "settings", Settings(
        _env_file=None, MYSQL_HOST="", MYSQL_USER="", MYSQL_PASSWORD="",
    ))
    with pytest.raises(MissingConfigurationError) as caught:
        database.async_session_maker()
    assert caught.value.service == "mysql"
    assert "MYSQL_HOST" in caught.value.missing_fields


def test_special_password_url_and_lazy_pool(monkeypatch):
    password = "a@b:/?#%+ secret"
    config = Settings(
        _env_file=None, MYSQL_HOST="database.invalid", MYSQL_DATABASE="test_db",
        MYSQL_USER="test-user", MYSQL_PASSWORD=password, MYSQL_SSL_ENABLED=False,
    )
    engine = Mock()
    engine.dispose = AsyncMock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(database, "settings", config)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(database, "create_async_engine", factory)
    assert database.get_engine() is engine
    assert database.get_engine() is engine
    factory.assert_called_once()
    url = factory.call_args.args[0]
    assert url.password == password
    assert url.database == "test_db"
    assert password not in str(url)
    assert factory.call_args.kwargs["hide_parameters"] is True
    assert factory.call_args.kwargs["echo"] is False
    asyncio.run(database.close_db())
    asyncio.run(database.close_db())
    engine.dispose.assert_awaited_once()


def test_tls_verifies_certificates(monkeypatch):
    import ssl

    factory = Mock()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(database, "settings", Settings(
        _env_file=None, MYSQL_HOST="db.invalid", MYSQL_USER="user",
        MYSQL_PASSWORD="test", MYSQL_SSL_ENABLED=True, MYSQL_SSL_CA="",
    ))
    monkeypatch.setattr(database, "create_async_engine", factory)
    database.get_engine()
    context = factory.call_args.kwargs["connect_args"]["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_twelve_tables_and_repeatable_version(engine):
    initialize(engine)
    initialize(engine)
    assert len(Base.metadata.tables) == 12
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"schema_versions"}
    with engine.connect() as connection:
        assert connection.execute(select(schema_versions.c.version)).scalars().all() == [1, 2, 3, 4]


def test_v3_sqlite_backfills_historical_rows():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE media_tags (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36),
                    media_id VARCHAR(36) NOT NULL,
                    category VARCHAR(50),
                    tag_name VARCHAR(100),
                    confidence FLOAT,
                    is_manual INTEGER,
                    created_at DATETIME
                )
            """))
            connection.execute(text("""
                CREATE TABLE import_tasks (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36),
                    task_id VARCHAR(36),
                    tos_directory VARCHAR(2048),
                    status VARCHAR(20),
                    total_files INTEGER,
                    processed_files INTEGER,
                    failed_files INTEGER,
                    error_message TEXT,
                    created_at DATETIME,
                    completed_at DATETIME
                )
            """))
            connection.execute(text(
                "INSERT INTO media_tags "
                "(id, user_id, media_id, category, tag_name) "
                "VALUES ('tag-1', 'user-1', 'media-1', 'road', '交叉路口')"
            ))
            connection.execute(text(
                "INSERT INTO import_tasks "
                "(id, user_id, task_id, tos_directory) "
                "VALUES ('import-1', 'user-1', 'task-1', 'tos://sample/')"
            ))
            _sqlite_upgrade_v3(connection)
            tag = connection.execute(text(
                "SELECT source FROM media_tags WHERE id = 'tag-1'"
            )).one()
            task = connection.execute(text(
                "SELECT tag_mode, custom_tag_prompt FROM import_tasks "
                "WHERE id = 'import-1'"
            )).one()
        assert tag.source == "default"
        assert task.tag_mode == "default"
        assert task.custom_tag_prompt is None
        tag_indexes = {
            tuple(index["column_names"])
            for index in inspect(engine).get_indexes("media_tags")
        }
        assert ("user_id", "source", "category", "tag_name") in tag_indexes
    finally:
        engine.dispose()


def test_v3_mysql_upgrade_emits_portable_ddl():
    connection = Mock()
    connection.dialect = mysql.dialect()

    _mysql_upgrade_v3(connection)

    statements = "\n".join(str(call.args[0]) for call in connection.execute.call_args_list)
    assert "media_tags" in statements
    assert "source VARCHAR(20) NOT NULL DEFAULT 'default'" in statements
    assert "user_id, source, category, tag_name" in statements
    assert "tag_mode VARCHAR(20) NOT NULL DEFAULT 'default'" in statements
    assert "custom_tag_prompt TEXT NULL" in statements


def test_mysql_ddl_compiles_without_database_creation():
    statements = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=mysql.dialect())))
        statements.extend(str(CreateIndex(index).compile(dialect=mysql.dialect())) for index in table.indexes)
    ddl = "\n".join(statements)
    assert "CREATE DATABASE" not in ddl
    assert "utf8mb4_bin" in ddl
    assert "BIGINT" in ddl
    assert "tos_url" in ddl
    assert "vector_instruction_version" in ddl
    assert "oss_url" not in ddl
    for table in Base.metadata.sorted_tables:
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"


def test_immutable_baseline_remains_v1():
    assert "user_id" not in baseline_metadata.tables["media_files"].columns
    assert "is_demo" not in baseline_metadata.tables["users"].columns
    assert "user_id" in Base.metadata.tables["media_files"].columns
    assert "is_demo" in Base.metadata.tables["users"].columns
    assert "source" not in baseline_metadata.tables["media_tags"].columns
    assert "tag_mode" not in baseline_metadata.tables["import_tasks"].columns
    assert "source" in Base.metadata.tables["media_tags"].columns
    assert "custom_tag_prompt" in Base.metadata.tables["import_tasks"].columns


def test_legacy_or_malformed_schema_is_not_adopted(engine):
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE media_files (id VARCHAR(36) PRIMARY KEY, oss_url VARCHAR(500))"))
    with pytest.raises(SchemaConflictError):
        initialize(engine)
    assert "schema_versions" not in inspect(engine).get_table_names()
    assert "oss_url" in {column["name"] for column in inspect(engine).get_columns("media_files")}


def test_missing_unique_index_is_not_swallowed(engine):
    initialize(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_users_username"))
    with pytest.raises(SchemaConflictError, match="unique"):
        initialize(engine)


def test_versioned_missing_table_is_conflict_not_recreated(engine):
    initialize(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE media_tags"))
    with pytest.raises(SchemaConflictError, match="missing"):
        initialize(engine)
    assert "media_tags" not in inspect(engine).get_table_names()


def test_unknown_version_is_rejected(engine):
    initialize(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE schema_versions SET version = 999 WHERE version = 2"))
    with pytest.raises(SchemaConflictError, match="history"):
        initialize(engine)


def test_partial_mysql_style_initialization_can_resume(engine):
    with engine.begin() as connection:
        baseline_metadata.tables["users"].create(connection)
    initialize(engine)
    initialize(engine)
    assert len(inspect(engine).get_table_names()) == 13


def test_unique_constraints_and_settings_crud(engine):
    initialize(engine)
    with Session(engine) as session:
        user = User(username="tester", password_hash="existing-hash", role="admin")
        session.add(user)
        session.flush()
        config = UserSystemSettings(
            user_id=user.id, tos_bucket_name="test-bucket", tos_access_key_secret="test-secret",
            ark_api_key="test-ark", embedding_model="doubao-embedding-vision-251215",
            embedding_dimension=1024, tag_model="doubao-seed-2-1-lite-260915",
        )
        session.add(config)
        session.commit()
        config.tos_bucket_name = "new-bucket"
        session.commit()
        assert session.scalar(select(UserSystemSettings)).tos_access_key_secret == "test-secret"
        session.add(UserSystemSettings(user_id=user.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.delete(config)
        session.commit()
        assert session.scalar(select(UserSystemSettings)) is None
        session.add(User(username="tester", password_hash="different-hash"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_repeat_init_preserves_hash_uuid_manual_tags_and_vector_identity(engine):
    initialize(engine)
    media_id = "00000000-0000-0000-0000-000000000001"
    with Session(engine) as session:
        media = MediaFile(
            id=media_id, user_id="user-id", tos_url="tos://test/a+%23.jpg",
            vector_status="done", vector_id="stable-id",
            vector_model="doubao-embedding-vision-251215", vector_dimension=1024,
            vector_instruction_version="road-scene-corpus-v1", vector_collection="media_vectors_v1",
        )
        session.add_all([
            media, MediaTag(
                user_id="user-id", media_id=media.id,
                category="road", tag_name="manual", is_manual=1,
            ),
            User(id="user-id", username="old-user", password_hash="unchanged-hash", role="admin"),
        ])
        session.commit()
    initialize(engine)
    with Session(engine) as session:
        assert session.get(User, "user-id").password_hash == "unchanged-hash"
        assert session.scalar(select(MediaTag)).is_manual == 1
        assert session.scalar(select(MediaTag)).source == "default"
        assert session.get(MediaFile, media_id).vector_dimension == 1024


def test_tag_source_and_import_mode_defaults_and_constraints(engine):
    initialize(engine)
    with Session(engine) as session:
        session.add_all([
            MediaTag(
                id="tag-default", user_id="user-1", media_id="media-1",
                category="road", tag_name="交叉路口",
            ),
            ImportTask(
                id="task-default", user_id="user-1", task_id="task-1",
                tos_directory="tos://sample/",
            ),
        ])
        session.commit()
        assert session.get(MediaTag, "tag-default").source == "default"
        task = session.get(ImportTask, "task-default")
        assert task.tag_mode == "default"
        assert task.custom_tag_prompt is None

        session.add(MediaTag(
            id="tag-invalid", user_id="user-1", media_id="media-1",
            source="unknown", category="road", tag_name="invalid",
        ))
        with pytest.raises(IntegrityError):
            session.commit()


def test_init_propagates_schema_conflict_and_sanitizes_driver_error(monkeypatch):
    import app.models.migrations as migrations

    monkeypatch.setattr(database, "get_engine", Mock())
    migration = AsyncMock(side_effect=SchemaConflictError("Schema column conflict: users"))
    monkeypatch.setattr(migrations, "migrate", migration)
    with pytest.raises(SchemaConflictError):
        asyncio.run(database.init_db())
    migration.side_effect = OperationalError("secret SQL", {}, Exception("password-secret"))
    with pytest.raises(ServiceError) as caught:
        asyncio.run(database.init_db())
    assert caught.value.service == "mysql"
    assert "secret" not in str(caught.value)


def test_request_dependency_rolls_back_without_exposing_sql(monkeypatch):
    session = AsyncMock()
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "async_session_maker", Mock(return_value=context))

    async def request():
        dependency = database.get_session()
        assert await anext(dependency) is session
        with pytest.raises(ServiceError) as caught:
            await dependency.athrow(OperationalError("secret SQL", {}, Exception("private-password")))
        assert "private-password" not in str(caught.value)
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()

    asyncio.run(request())


@pytest.mark.parametrize("fail", [False, True])
def test_mysql_migration_lock_released_after_commit_or_rollback(fail):
    from app.models.migrations import migrate

    connection = Mock()
    connection.dialect.name = "mysql"
    connection.scalar = AsyncMock(return_value=1)
    connection.run_sync = AsyncMock(side_effect=SchemaConflictError("conflict") if fail else None)
    connection.commit = AsyncMock()
    connection.rollback = AsyncMock()
    connection.execute = AsyncMock()
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    engine = Mock()
    engine.url.database = "test-db"
    engine.connect.return_value = context
    if fail:
        with pytest.raises(SchemaConflictError):
            asyncio.run(migrate(engine))
        connection.rollback.assert_awaited_once()
    else:
        asyncio.run(migrate(engine))
        connection.rollback.assert_not_awaited()
    assert "GET_LOCK" in str(connection.scalar.call_args.args[0])
    assert "RELEASE_LOCK" in str(connection.execute.call_args.args[0])
    connection.run_sync.assert_awaited_once_with(apply_migrations)
