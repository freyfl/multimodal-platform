"""Readiness and statistics must distinguish an empty store from an outage."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.errors import MissingConfigurationError, ServiceError
from test_settings_router import api_modules, client, config, db  # Shared scoped fixtures.


async def test_public_config_and_liveness_do_not_probe_dependencies(
    client, api_modules, monkeypatch,
):
    for name in ("tos_service", "milvus_service"):
        monkeypatch.setattr(api_modules.system_router, name, SimpleNamespace(
            check_connection=AsyncMock(side_effect=AssertionError("must not probe")),
        ))
    monkeypatch.setattr(api_modules.system_router, "async_session_maker", Mock(
        side_effect=AssertionError("must not connect"),
    ))
    assert (await client.get("/api/system/health")).json()["data"]["status"] == "ok"
    response = await client.get("/api/system/config")
    data = response.json()["data"]
    assert set(data) == {"apiPrefix", "appName", "version", "model_catalog"}
    assert data["model_catalog"]["defaults"]["embedding_dimension"] == 1024
    assert "global-secret" not in response.text
    assert "global-ark-key" not in response.text


@pytest.mark.parametrize("failure", [None, "tos", "mysql", "milvus"])
async def test_readiness_checks_all_dependencies_without_models(
    client, api_modules, db, monkeypatch, failure,
):
    checks = {}
    for name in ("tos", "milvus"):
        check = AsyncMock(return_value={"status": "ready"})
        if failure == name:
            check.side_effect = ServiceError(name, "timeout", request_id="req-123")
        checks[name] = check
        monkeypatch.setattr(api_modules.system_router, f"{name}_service", SimpleNamespace(check_connection=check))
    factory = Mock(return_value=db)
    if failure == "mysql":
        factory.side_effect = MissingConfigurationError("mysql", ["MYSQL_HOST"])
    monkeypatch.setattr(api_modules.system_router, "async_session_maker", factory)
    for name in ("embedding_service", "tag_service"):
        monkeypatch.setattr(api_modules.settings_router, name, SimpleNamespace(
            check_connection=AsyncMock(side_effect=AssertionError("billable probe forbidden")),
        ))
    response = await client.get("/api/system/readiness")
    assert response.status_code == (503 if failure else 200)
    assert response.json()["code"] == response.status_code
    services = response.json()["data"]["services"]
    assert set(services) == {"tos", "mysql", "milvus"}
    for name, check in checks.items():
        check.assert_awaited_once()
    factory.assert_called_once()
    if failure:
        assert services[failure]["status"] == "unavailable"
        assert services[failure]["error"]["service"] == failure
    else:
        assert "SELECT 1" in db.statements


async def test_readiness_never_echoes_raw_failure(client, api_modules, monkeypatch):
    for name in ("tos", "milvus"):
        monkeypatch.setattr(api_modules.system_router, f"{name}_service", SimpleNamespace(
            check_connection=AsyncMock(side_effect=RuntimeError("password=secret?signature=secret")),
        ))
    monkeypatch.setattr(api_modules.system_router, "async_session_maker", Mock(
        side_effect=RuntimeError("mysql://secret"),
    ))
    response = await client.get("/api/system/readiness")
    assert response.status_code == 503
    assert "secret" not in response.text
    assert all(value["error"]["category"] == "unavailable"
               for value in response.json()["data"]["services"].values())


async def seed_stats(db):
    await db.execute(text(
        "INSERT INTO media_files (id, user_id, tos_url, file_type, file_size) VALUES "
        "('image', 'user-a', 'tos://bucket/a.jpg', 'image', 1073741824), "
        "('video', 'user-a', 'tos://bucket/a.mp4', 'video', 2147483648), "
        "('unknown', 'user-a', 'tos://bucket/a.bin', NULL, NULL)"
    ))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    for task_id, status, finished in [
        ("running", "running", None), ("pending", "pending", None),
        ("today", "completed", today), ("future", "completed", today + timedelta(days=1)),
        ("old", "completed", today - timedelta(seconds=1)), ("failed", "failed", today),
    ]:
        await db.execute(text(
            "INSERT INTO import_tasks (id, user_id, task_id, status, completed_at) "
            "VALUES (:id, 'user-a', :id, :status, :finished)"
        ), {"id": task_id, "status": status, "finished": finished})
    for kind in ("tag", "text", "image", "unknown"):
        await db.execute(text(
            "INSERT INTO search_history (id, user_id, search_type) "
            "VALUES (:kind, 'user-a', :kind)"
        ), {"kind": kind})
    await db.commit()


@pytest.mark.parametrize("populated", [False, True])
async def test_stats_standard_aggregates_and_exact_vector_count(
    client, api_modules, db, monkeypatch, populated,
):
    if populated:
        await seed_stats(db)
    db.statements.clear()
    count = AsyncMock(return_value=7 if populated else 0)
    monkeypatch.setattr(api_modules.system_router, "milvus_service", SimpleNamespace(get_vector_count=count))
    response = await client.get("/api/system/stats")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["media"] == {
        "total": 3 if populated else 0, "videos": int(populated), "images": int(populated),
        "storage_used_gb": 3.0 if populated else 0.0,
    }
    assert data["tasks"] == {key: int(populated) for key in ("running", "pending", "completed_today")}
    assert data["performance"] == {
        "total_searches": 4 if populated else 0,
        "tag_searches": int(populated),
        "text_searches": int(populated),
        "image_searches": int(populated),
    }
    assert data["vectors"] == {
        "total": 7 if populated else 0,
        "dimension": 1024,
        "count_is_exact": True,
    }
    count.assert_awaited_once_with("user-a")
    assert len(db.statements) == 3
    assert all("SUM(" in statement for statement in db.statements)


@pytest.mark.parametrize("failure", ["mysql", "milvus", "invalid_count"])
async def test_stats_failure_is_not_reported_as_an_empty_database(
    client, api_modules, db, monkeypatch, failure,
):
    count = AsyncMock(return_value=0)
    if failure == "mysql":
        monkeypatch.setattr(db, "execute", AsyncMock(side_effect=OperationalError(
            "SQL secret", {}, Exception("secret"),
        )))
    elif failure == "milvus":
        count.side_effect = RuntimeError("secret-token")
    else:
        count.return_value = -1
    monkeypatch.setattr(api_modules.system_router, "milvus_service", SimpleNamespace(get_vector_count=count))
    response = await client.get("/api/system/stats")
    assert response.status_code == 503
    assert response.json()["code"] != 200
    assert "vectors" not in response.json()["data"]
    assert "secret" not in response.text


async def test_admin_stats_use_global_scope(api_modules, db, monkeypatch):
    await seed_stats(db)
    await db.execute(text(
        "INSERT INTO media_files "
        "(id, user_id, tos_url, file_type, file_size) VALUES "
        "('other-image', 'user-b', 'tos://other/private.jpg', 'image', 1)"
    ))
    await db.commit()
    count = AsyncMock(return_value=8)
    monkeypatch.setattr(
        api_modules.system_router, "milvus_service",
        SimpleNamespace(get_vector_count=count),
    )
    response = await api_modules.system_router.get_system_stats(
        {"id": "admin", "role": "admin"}, db,
    )
    assert response.data.media["total"] == 4
    assert response.data.vectors["total"] == 8
    count.assert_awaited_once_with(None)


async def test_dashboard_effective_bucket_and_latest_tos_directory(
    client, api_modules, db,
):
    await client.put("/api/settings/me", json={"tos_bucket_name": "custom-bucket"})
    for task_id, date, directory in [
        ("old", "2026-09-15 10:00:00", "tos://custom-bucket/one/"),
        ("new", "2026-09-16 10:00:00", "tos://custom-bucket/one/"),
        ("other", "2026-09-17 10:00:00", "tos://custom-bucket/two/"),
        ("blank", "2026-09-18 10:00:00", ""),
    ]:
        await db.execute(text(
            "INSERT INTO import_tasks "
            "(id, user_id, task_id, tos_directory, created_at, status, total_files, processed_files) "
            "VALUES (:id, 'user-a', :id, :directory, :date, 'completed', 2, 2)"
        ), {"id": task_id, "directory": directory, "date": date})
    response = await client.get("/api/system/dashboard")
    data = response.json()["data"]
    assert data["bucket"]["bucket_name"] == "custom-bucket"
    assert data["bucket"]["endpoint"] is None
    assert [row["task_id"] for row in data["imported_dirs"]] == ["other", "new"]
    assert all("tos_directory" in row and "oss_directory" not in row for row in data["imported_dirs"])
    assert "global-secret" not in response.text


async def test_dashboard_database_error_does_not_fake_empty_history(
    api_modules, config,
):
    session = SimpleNamespace(execute=AsyncMock(side_effect=OperationalError(
        "sensitive SQL", {}, Exception("secret"),
    )))
    with pytest.raises(ServiceError) as captured:
        await api_modules.system_router.get_dashboard_info(
            session, {"id": "user-a"}, api_modules.deps.effective_user_settings(),
        )
    assert captured.value.service == "mysql"
