"""Offline safety tests for the destructive maintenance utility."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.config import Settings
from scripts import clear_all_data as cleanup


def configured_settings(**updates):
    values = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_DATABASE": "application_db",
        "MYSQL_USER": "operator",
        "MYSQL_PASSWORD": "mysql-secret-value",
        "MILVUS_URI": "https://milvus.internal:19530",
        "MILVUS_DB_NAME": "vector_db",
        "MILVUS_COLLECTION": "media_vectors_v1",
        "MILVUS_TOKEN": "milvus-secret-value",
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


async def invoke(arguments, **kwargs):
    messages = []
    code = await cleanup.run(arguments, output=messages.append, **kwargs)
    return code, "\n".join(messages)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--target", "mysql"],
        ["--mysql-database", "application_db"],
        ["--target", "mysql", "--target", "mysql", "--mysql-database", "application_db"],
        ["--target", "milvus", "--milvus-database", "vector_db"],
    ],
)
async def test_incomplete_or_ambiguous_targets_are_refused_without_connections(arguments):
    mysql = AsyncMock()
    milvus = Mock()

    code, report = await invoke(
        arguments,
        config=configured_settings(),
        mysql_cleaner=mysql,
        milvus_cleaner=milvus,
    )

    assert code == 2
    assert "REFUSED" in report
    mysql.assert_not_awaited()
    milvus.assert_not_called()


async def test_default_mode_reports_exact_targets_without_connections():
    mysql = AsyncMock()
    milvus = Mock()
    arguments = [
        "--target", "milvus",
        "--milvus-database", "vector_db",
        "--milvus-collection", "media_vectors_v1",
    ]

    code, report = await invoke(
        arguments,
        config=configured_settings(),
        mysql_cleaner=mysql,
        milvus_cleaner=milvus,
    )

    assert code == 0
    assert "DRY-RUN" in report
    assert "database=vector_db" in report
    assert "collection=media_vectors_v1" in report
    assert "collection retained" in report
    assert "Required confirmation: DELETE:milvus/vector_db/media_vectors_v1" in report
    mysql.assert_not_awaited()
    milvus.assert_not_called()


@pytest.mark.parametrize("confirmation", [None, "DELETE", "DELETE:mysql/other_db"])
async def test_execute_requires_exact_target_bound_confirmation(confirmation):
    mysql = AsyncMock()
    arguments = [
        "--target", "mysql",
        "--mysql-database", "application_db",
        "--execute",
    ]
    if confirmation is not None:
        arguments.extend(["--confirm", confirmation])

    code, report = await invoke(
        arguments,
        config=configured_settings(),
        mysql_cleaner=mysql,
    )

    assert code == 2
    assert "does not exactly match" in report
    mysql.assert_not_awaited()


async def test_all_targets_are_validated_before_either_cleanup_starts():
    config = configured_settings(MILVUS_URI="")
    mysql = AsyncMock()
    milvus = Mock()
    arguments = [
        "--target", "mysql",
        "--mysql-database", "application_db",
        "--target", "milvus",
        "--milvus-database", "vector_db",
        "--milvus-collection", "media_vectors_v1",
        "--execute",
        "--confirm", "DELETE:mysql/application_db+milvus/vector_db/media_vectors_v1",
    ]

    code, report = await invoke(
        arguments,
        config=config,
        mysql_cleaner=mysql,
        milvus_cleaner=milvus,
    )

    assert code == 2
    assert "MILVUS_URI" in report
    assert "mysql-secret-value" not in report
    assert "milvus-secret-value" not in report
    mysql.assert_not_awaited()
    milvus.assert_not_called()


async def test_explicit_target_must_match_configuration():
    mysql = AsyncMock()
    arguments = [
        "--target", "mysql",
        "--mysql-database", "lookalike_db",
        "--execute",
        "--confirm", "DELETE:mysql/lookalike_db",
    ]

    code, report = await invoke(
        arguments,
        config=configured_settings(),
        mysql_cleaner=mysql,
    )

    assert code == 2
    assert "does not match configured target" in report
    assert "127.0.0.1" not in report
    mysql.assert_not_awaited()


async def test_authorized_services_run_and_report_separately():
    mysql = AsyncMock(return_value={"users": 2, "media_files": 3})
    milvus = Mock(return_value=4)
    arguments = [
        "--target", "milvus",
        "--milvus-database", "vector_db",
        "--milvus-collection", "media_vectors_v1",
        "--target", "mysql",
        "--mysql-database", "application_db",
        "--execute",
        "--confirm", "DELETE:mysql/application_db+milvus/vector_db/media_vectors_v1",
    ]

    code, report = await invoke(
        arguments,
        config=configured_settings(),
        mysql_cleaner=mysql,
        milvus_cleaner=milvus,
    )

    assert code == 0
    assert "RESULT mysql: deleted=5" in report
    assert "RESULT milvus: deleted=4" in report
    assert "collection_retained=true" in report
    mysql.assert_awaited_once()
    milvus.assert_called_once()


async def test_runtime_errors_are_reported_without_sensitive_details():
    async def fail(_config):
        raise RuntimeError("mysql-secret-value at 127.0.0.1")

    arguments = [
        "--target", "mysql",
        "--mysql-database", "application_db",
        "--execute",
        "--confirm", "DELETE:mysql/application_db",
    ]

    code, report = await invoke(
        arguments,
        config=configured_settings(),
        mysql_cleaner=fail,
    )

    assert code == 1
    assert "RESULT mysql: failed" in report
    assert "mysql-secret-value" not in report
    assert "127.0.0.1" not in report


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


async def test_mysql_cleanup_deletes_registered_tables_in_one_transaction():
    connection = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        execute=AsyncMock(),
    )
    engine = SimpleNamespace(
        begin=Mock(return_value=AsyncContext(connection)),
        dispose=AsyncMock(),
    )

    result = await cleanup.clear_mysql_records(
        configured_settings(),
        engine_factory=lambda _config: engine,
    )

    assert set(result) == {
        "annotation_frames", "annotation_runs",
        "annotation_result_sets", "annotation_result_set_members",
        "media_files", "media_tags", "import_tasks", "search_history",
        "users", "login_logs", "user_sessions", "user_system_settings",
    }
    assert all(count == 1 for count in result.values())
    assert connection.scalar.await_count == 12
    assert connection.execute.await_count == 12
    engine.begin.assert_called_once_with()
    engine.dispose.assert_awaited_once_with()


def test_milvus_cleanup_deletes_entities_and_retains_collection():
    client = Mock()
    client.has_collection.return_value = True
    client.query.side_effect = [[{"count(*)": 7}], [{"count(*)": 0}]]
    client.delete.return_value = {"delete_count": 7}

    count = cleanup.clear_milvus_records(
        configured_settings(),
        client_factory=lambda _config: client,
    )

    assert count == 7
    client.delete.assert_called_once_with(
        collection_name="media_vectors_v1",
        filter='media_id >= ""',
        timeout=30,
    )
    assert not hasattr(client, "drop_collection") or not client.drop_collection.called
    client.close.assert_called_once_with()


def test_missing_milvus_collection_is_a_noop_and_client_is_closed():
    client = Mock()
    client.has_collection.return_value = False

    count = cleanup.clear_milvus_records(
        configured_settings(),
        client_factory=lambda _config: client,
    )

    assert count == 0
    client.query.assert_not_called()
    client.delete.assert_not_called()
    client.close.assert_called_once_with()


def test_cleanup_script_contains_no_retired_runtime_names():
    source = (
        Path(__file__).parents[1] / "scripts" / "clear_all_data.py"
    ).read_text(encoding="utf-8").lower()

    assert "lindorm" not in source
    assert "oss" not in source
    assert "drop_collection" not in source
