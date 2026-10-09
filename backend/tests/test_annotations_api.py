"""T5 API integration: real SQLite/FastAPI, private PNG, mocked TOS/jobs."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import delete, event, func, insert, select, update
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import annotations_router, deps
from app.errors import MissingConfigurationError, ServiceError
from app.models.annotation_schemas import AnnotationOptions
from app.models.database import Base, get_session
from app.models.models import (
    AnnotationFrame, AnnotationResultSet, AnnotationResultSetMember, AnnotationRun,
    MediaFile, MediaTag, User, UserSystemSettings,
)
from app.services import annotation_query_service as query_module
from app.services.annotation_rules import build_rule_snapshot
from app.services.search_service import exact_text


PREFIX = "/api/annotations"
SOURCE = {"tags": [{"source": "default", "category": "road", "name": "highway"}], "logic": "AND"}
NOW = datetime(2026, 9, 19, 12)
OBJECT = {
    "object_id": "object-1", "category": "vehicle", "name": "car", "confidence": 0.8,
    "bbox_2d": [0.1, 0.2, 0.5, 0.6], "cuboid_3d": None,
    "cuboid_unavailable_reason": "not_requested", "occluded": False, "truncated": False,
}


def run_record(identity, owner, media, revision=1, status="completed"):
    snapshot = build_rule_snapshot(
        AnnotationOptions(annotation_box_mode="2d"),
        model="doubao-seed-2-1-lite-260915", source_etag="etag", source_version=None,
    ).model_dump(mode="json")
    return AnnotationRun(
        id=identity, user_id=owner, media_id=media, revision=revision,
        status=status, snapshot=snapshot, idempotency_hash=snapshot["rule_hash"],
        planned_frames=24, processed_frames=24, completed_frames=24, failed_frames=0,
        created_at=NOW, updated_at=NOW,
    )


@pytest.fixture
async def api(monkeypatch, tmp_path, empty_settings):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    config = empty_settings.model_copy(update={
        "TOS_BUCKET_NAME": "deployment-bucket",
        "TOS_ACCESS_KEY_ID": "deployment-ak", "TOS_ACCESS_KEY_SECRET": "deployment-secret",
        "ANNOTATION_STORAGE_DIR": str(tmp_path / "frames"),
        "ANNOTATION_TEMP_DIR": str(tmp_path / "work"),
    })
    monkeypatch.setattr(deps, "settings", config)
    monkeypatch.setattr(query_module, "settings", config)
    monkeypatch.setattr(deps, "verify_token", lambda token: {"type": "access", "sub": token})
    monkeypatch.setattr(query_module, "_now", lambda: NOW.replace(tzinfo=timezone.utc))
    storage = tmp_path / "frames"
    async with sessions() as session:
        for owner, role in (("owner", "user"), ("other", "user"), ("admin", "admin")):
            session.add(User(
                id=owner, username=owner, email=f"{owner}@example.invalid",
                password_hash="offline", role=role, is_active=1,
            ))
            session.add(UserSystemSettings(
                user_id=owner, tos_bucket_name=f"{owner}-bucket",
                tos_access_key_id=f"{owner}-ak", tos_access_key_secret=f"{owner}-secret",
                tos_endpoint="https://tos.invalid", tos_region="cn-beijing",
            ))
        await session.flush()
        for index in range(45):
            name = {0: "same.png", 1: "same.png", 2: "road,night.png", 3: "Case.png"}.get(
                index, f"file-{index:02}.png",
            )
            session.add(MediaFile(
                id=f"media-{index:02}", user_id="owner",
                tos_url=f"tos://owner-bucket/{index}/{name}",
                file_name=name, file_type="video" if index == 0 else "image",
                created_at=NOW, updated_at=NOW,
            ))
            session.add(MediaTag(
                user_id="owner", media_id=f"media-{index:02}",
                source="default", category="road", tag_name="highway",
            ))
        session.add(MediaFile(
            id="foreign", user_id="other", tos_url="tos://other-bucket/private.png",
            file_name="same.png", file_type="image", created_at=NOW,
        ))
        session.add(MediaTag(
            user_id="other", media_id="foreign", source="default", category="road", tag_name="highway",
        ))
        session.add(MediaTag(
            user_id="owner", media_id="media-00", source="custom", category="road", tag_name="highway",
        ))
        # Forged tag ownership must never authorize either search path.
        session.add(MediaTag(
            user_id="other", media_id="media-00", source="custom", category="private", tag_name="secret",
        ))
        await session.flush()
        session.add_all([
            run_record("published", "owner", "media-00"),
            run_record("latest", "owner", "media-00", revision=2, status="partial"),
            run_record("foreign-run", "other", "foreign"),
        ])
        await session.flush()
        for index in range(24):
            session.add(AnnotationFrame(
                id=f"frame-{index:02}", user_id="owner", run_id="published",
                frame_index=index, timestamp_ms=index * 1033.5,
                width=100, height=50, status="completed", objects=[OBJECT],
            ))
        session.add(AnnotationFrame(
            id="latest-frame", user_id="owner", run_id="latest", frame_index=0,
            timestamp_ms=0, width=100, height=50, status="failed",
            objects=[], error="PRIVATE prompt https://private/?Signature=secret",
        ))
        session.add(AnnotationFrame(
            id="foreign-frame", user_id="other", run_id="foreign-run", frame_index=0,
            timestamp_ms=None, width=100, height=50, status="completed", objects=[],
        ))
        await session.execute(update(MediaFile).where(MediaFile.id == "media-00").values(
            published_annotation_run_id="published", annotation_status="partial",
        ))
        await session.commit()

    key = f"owner/media-00/published/{'a' * 32}.png"
    path = storage / key
    path.parent.mkdir(parents=True)
    Image.new("RGB", (100, 50), "red").save(path)
    async with sessions() as session:
        await session.execute(update(AnnotationFrame).where(AnnotationFrame.id == "frame-00").values(
            storage_key=key,
        ))
        await session.commit()
    borrowed = []
    sign = AsyncMock(return_value="https://owner-bucket.tos.invalid/media?Signature=mock")

    @asynccontextmanager
    async def borrow(config):
        borrowed.append(dict(config))
        if not config.get("tos_access_key_id"):
            raise MissingConfigurationError("tos", ["TOS_ACCESS_KEY_ID"])
        yield SimpleNamespace(bucket_name=config["tos_bucket_name"], get_preview_url=sign)

    monkeypatch.setattr(query_module, "borrow_tos", borrow)
    jobs = AsyncMock(return_value={
        "task_id": "task-1", "status": "pending", "media_ids": ["media-00"], "run_ids": ["job-run"],
    })
    monkeypatch.setattr(annotations_router, "submit_annotation_job", jobs)
    app = FastAPI()
    app.include_router(annotations_router.router, prefix="/api")

    async def session_dependency():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": "Bearer owner"},
    ) as client:
        yield SimpleNamespace(
            app=app, client=client, sessions=sessions, engine=engine,
            borrowed=borrowed, sign=sign, jobs=jobs, path=path, storage=storage,
        )
    await engine.dispose()


async def search(api, **body):
    return await api.client.post(f"{PREFIX}/search", json=body)


async def snapshot(api, source=None):
    response = await api.client.post(f"{PREFIX}/result-sets", json=source or SOURCE)
    assert response.status_code == 200, response.text
    return response.json()["data"]


ENDPOINTS = [
    ("GET", "/config", None), ("POST", "/search", {}),
    ("GET", "/media/media-00", None), ("GET", "/runs/published/frames", None),
    ("GET", "/frames/frame-00/image", None), ("GET", "/media/media-00/preview", None),
    ("POST", "/jobs", {"media_ids": ["media-00"]}),
    ("POST", "/result-sets", SOURCE), ("GET", "/result-sets/missing", None),
]


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
async def test_all_routes_require_bearer_and_wrap_errors(api, method, path, body):
    api.client.headers.pop("Authorization")
    response = await api.client.request(method, PREFIX + path, json=body)
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 401
    assert response.headers["www-authenticate"] == "Bearer"
    api.sign.assert_not_awaited()
    api.jobs.assert_not_awaited()


@pytest.mark.parametrize("path", [
    "/media/foreign", "/runs/foreign-run/frames", "/frames/foreign-frame/image",
    "/media/foreign/preview", "/media/missing", "/runs/missing/frames",
    "/frames/missing/image", "/media/missing/preview",
])
async def test_each_resource_id_isolation(api, path):
    response = await api.client.get(PREFIX + path)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == 404
    assert "other" not in response.text
    api.sign.assert_not_awaited()


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize("action", ["generate", "retry", "regenerate"])
async def test_jobs_only_owner_entire_batch_before_dispatch(api, role, action):
    api.client.headers["Authorization"] = f"Bearer {role}"
    response = await api.client.post(f"{PREFIX}/jobs", json={
        "media_ids": ["media-00", "foreign"], "action": action,
    })
    assert response.status_code == 404
    api.jobs.assert_not_awaited()


async def test_job_boundary_deduplicates_and_passes_schema(api):
    response = await api.client.post(f"{PREFIX}/jobs", json={"media_ids": ["media-00", "media-00"]})
    assert response.status_code == 200, response.text
    kwargs = api.jobs.call_args.kwargs
    assert kwargs["user_id"] == "owner"
    assert kwargs["request"].media_ids == ["media-00"]
    assert response.json()["data"]["task_id"] == "task-1"


async def test_list_stable_pagination_and_no_large_or_sensitive_fields(api):
    sql = []

    @event.listens_for(api.engine.sync_engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    ids = []
    for page, count in [(1, 20), (2, 20), (3, 5), (4, 0)]:
        response = await search(api, page=page)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 45 and data["size"] == 20
        assert len(data["results"]) == count
        ids.extend(item["media_id"] for item in data["results"])
        assert "prompt" not in response.text and "objects" not in response.text
        assert "snapshot" not in response.text and "storage_key" not in response.text
        assert all(item["user_id"] is None for item in data["results"])
    assert ids == [f"media-{index:02}" for index in reversed(range(45))]
    assert not any("annotation_frames.objects," in statement for statement in sql)
    api.sign.assert_not_awaited()


async def test_filename_csv_exact_basename_or_and_filters(api):
    response = await search(api, filenames=' same.png，"road,night.png"\nsame.png,,')
    assert response.status_code == 200, response.text
    assert {item["media_id"] for item in response.json()["data"]["results"]} == {
        "media-00", "media-01", "media-02",
    }
    response = await search(api, filenames="same.png", file_type="video", status="partial")
    assert [item["media_id"] for item in response.json()["data"]["results"]] == ["media-00"]
    for name in ["case.png", "same", "road%", "same.png " * 2]:
        assert (await search(api, filenames=name)).json()["data"]["total"] == 0
    assert (await search(api, filenames=" ,，\n ")).json()["data"]["total"] == 45


@pytest.mark.parametrize("body", [
    {"filenames": "x" * 256}, {"filenames": ",".join(f"{n}.png" for n in range(101))},
    {"filenames": "../same.png"}, {"filenames": "path/same.png"},
    {"filenames": '"not-closed'}, {"page": 0}, {"page": True}, {"size": 101},
    {"size": 0}, {"status": "unknown"}, {"url": "http://private/?Signature=SECRET"},
])
async def test_search_limits_and_sanitized_validation(api, body):
    response = await search(api, **body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == 422
    assert "SECRET" not in response.text


async def test_filename_maxima_accepted(api):
    response = await search(api, filenames=",".join(f"{index}.png" for index in range(100)), size=100)
    assert response.status_code == 200
    assert (await search(api, filenames="x" * 255)).status_code == 200


async def test_detail_retains_published_and_latest_frames_paginate(api):
    response = await api.client.get(f"{PREFIX}/media/media-00")
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    assert detail["published_run"]["id"] == "published"
    assert detail["latest_run"]["id"] == "latest"
    assert detail["media"]["object_count"] == 24
    assert detail["media"]["status"] == "partial"
    assert "prompt" not in response.text and "objects" not in response.text
    first = (await api.client.get(f"{PREFIX}/runs/published/frames")).json()["data"]
    last = (await api.client.get(f"{PREFIX}/runs/published/frames?page=2")).json()["data"]
    assert first["total"] == last["total"] == 24
    assert len(first["results"]) == 20 and len(last["results"]) == 4
    assert last["results"][0]["timestamp_ms"] == 20670.0
    assert first["results"][0]["objects"] == [OBJECT]
    assert "storage_key" not in str(first)
    failed = await api.client.get(f"{PREFIX}/runs/latest/frames")
    assert "PRIVATE" not in failed.text and "Signature" not in failed.text
    assert failed.json()["data"]["results"][0]["objects"] == []
    assert (await api.client.get(f"{PREFIX}/runs/published/frames?size=101")).status_code == 422
    assert (await api.client.get(f"{PREFIX}/runs/published/frames?page=0")).status_code == 422


async def test_private_frame_binary_and_reused_storage_version(api):
    response = await api.client.get(f"{PREFIX}/frames/frame-00/image")
    assert response.status_code == 200, response.text
    assert response.content == api.path.read_bytes()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    async with api.sessions() as session:
        frame = await session.get(AnnotationFrame, "latest-frame")
        frame.storage_key = str(api.path.relative_to(api.storage))
        await session.commit()
    assert (await api.client.get(f"{PREFIX}/frames/latest-frame/image")).content == response.content


@pytest.mark.parametrize("storage_key", [
    "../../private", "other/media-00/published/" + "a" * 32 + ".png",
    "owner/foreign/published/" + "a" * 32 + ".png",
    "https://private.invalid/image.png",
])
async def test_frame_persisted_paths_cannot_escape_owner_media(api, storage_key):
    async with api.sessions() as session:
        frame = await session.get(AnnotationFrame, "frame-00")
        frame.storage_key = storage_key
        await session.commit()
    response = await api.client.get(f"{PREFIX}/frames/frame-00/image")
    assert response.status_code == 404


async def test_missing_frame_and_symlink_denied(api, tmp_path):
    api.path.unlink()
    assert (await api.client.get(f"{PREFIX}/frames/frame-00/image")).status_code == 404
    target = tmp_path / "outside.png"
    Image.new("RGB", (1, 1)).save(target)
    api.path.symlink_to(target)
    assert (await api.client.get(f"{PREFIX}/frames/frame-00/image")).status_code == 404


async def test_admin_global_reads_but_preview_uses_media_owner(api):
    api.client.headers["Authorization"] = "Bearer admin"
    response = await search(api, size=100)
    assert response.json()["data"]["total"] == 46
    assert {item["user_id"] for item in response.json()["data"]["results"]} == {"owner", "other"}
    assert (await api.client.get(f"{PREFIX}/media/foreign")).status_code == 200
    assert (await api.client.get(f"{PREFIX}/runs/foreign-run/frames")).status_code == 200
    assert (await api.client.get(f"{PREFIX}/frames/frame-00/image")).status_code == 200
    for _ in range(2):
        response = await api.client.get(f"{PREFIX}/media/foreign/preview")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["data"]["expires_at"] == "2026-09-19T13:00:00Z"
    assert all(config["tos_access_key_id"] == "other-ak" for config in api.borrowed)
    assert api.sign.call_args.args == ("tos://other-bucket/private.png",)


async def test_preview_without_owner_config_never_falls_back(api):
    api.client.headers["Authorization"] = "Bearer admin"
    async with api.sessions() as session:
        await session.execute(delete(UserSystemSettings).where(UserSystemSettings.user_id == "other"))
        await session.commit()
    response = await api.client.get(f"{PREFIX}/media/foreign/preview")
    assert response.status_code == 503
    assert response.json()["data"]["category"] == "not_configured"
    assert api.borrowed[0]["tos_access_key_id"] is None
    api.sign.assert_not_awaited()


async def test_preview_rejects_arbitrary_persisted_http_url(api):
    async with api.sessions() as session:
        media = await session.get(MediaFile, "media-00")
        media.tos_url = "http://127.0.0.1/internal"
        await session.commit()
    response = await api.client.get(f"{PREFIX}/media/media-00/preview")
    assert response.status_code == 400
    api.sign.assert_not_awaited()


async def test_snapshot_all_45_not_current_page_and_immutable(api):
    snap = await snapshot(api)
    assert snap["total"] == 45 and snap["source"] == SOURCE
    assert snap["created_at"] == "2026-09-19T12:00:00Z"
    assert snap["expires_at"] == "2026-09-20T12:00:00Z"
    identity = snap["result_set_id"]
    ids = []
    for page, count in [(1, 12), (2, 12), (3, 12), (4, 9)]:
        result = (await search(api, result_set_id=identity, page=page, size=12)).json()["data"]
        assert result["total"] == 45 and len(result["results"]) == count
        ids.extend(item["media_id"] for item in result["results"])
    assert len(set(ids)) == 45
    async with api.sessions() as session:
        await session.execute(delete(MediaTag).where(MediaTag.user_id == "owner"))
        session.add(MediaFile(
            id="new-match", user_id="owner", tos_url="tos://owner-bucket/new.png",
            file_name="new.png", file_type="image",
        ))
        session.add(MediaTag(
            user_id="owner", media_id="new-match", source="default", category="road", tag_name="highway",
        ))
        await session.commit()
    result = (await search(api, result_set_id=identity, size=100)).json()["data"]
    assert {item["media_id"] for item in result["results"]} == set(ids)
    result = (await search(api, result_set_id=identity, filenames="same.png", file_type="image")).json()["data"]
    assert [item["media_id"] for item in result["results"]] == ["media-01"]
    assert (await api.client.get(f"{PREFIX}/result-sets/{identity}")).json()["data"] == snap
    api.sign.assert_not_awaited()


async def test_snapshot_deletions_excluded_without_changing_metadata(api):
    snap = await snapshot(api)
    async with api.sessions() as session:
        await session.execute(delete(MediaFile).where(MediaFile.id == "media-44"))
        await session.commit()
    result = (await search(api, result_set_id=snap["result_set_id"])).json()["data"]
    assert result["total"] == 44
    metadata = (await api.client.get(f"{PREFIX}/result-sets/{snap['result_set_id']}")).json()["data"]
    assert metadata["total"] == 45
    assert metadata["expires_at"] == snap["expires_at"]


async def test_snapshot_source_category_name_and_or_exact(api):
    default, custom = SOURCE["tags"][0], {**SOURCE["tags"][0], "source": "custom"}
    assert (await snapshot(api, {"tags": [default, custom], "logic": "AND"}))["total"] == 1
    assert (await snapshot(api, {"tags": [default, custom], "logic": "OR"}))["total"] == 45
    for change in [
        {"category": "Road"}, {"name": "Highway"}, {"name": "highway "},
        {"category": "private", "name": "secret", "source": "custom"},
    ]:
        assert (await snapshot(api, {"tags": [{**default, **change}]}))["total"] == 0


async def test_snapshot_expiry_is_410_and_unauthorized_is_404_first(api, monkeypatch):
    snap = await snapshot(api)
    monkeypatch.setattr(query_module, "_now", lambda: (NOW + timedelta(hours=24)).replace(tzinfo=timezone.utc))
    for response in [
        await search(api, result_set_id=snap["result_set_id"]),
        await api.client.get(f"{PREFIX}/result-sets/{snap['result_set_id']}"),
    ]:
        assert response.status_code == 410 and response.json()["code"] == 410
        assert "expired" in response.json()["message"]
        assert "results" not in response.json()["data"]
    api.client.headers["Authorization"] = "Bearer other"
    assert (await search(api, result_set_id=snap["result_set_id"])).status_code == 404
    assert (await api.client.get(f"{PREFIX}/result-sets/{snap['result_set_id']}")).status_code == 404
    assert (await search(api, result_set_id="missing")).status_code == 404


async def test_snapshot_permissions_rechecked_after_role_and_media_owner_change(api):
    api.client.headers["Authorization"] = "Bearer admin"
    snap = await snapshot(api)
    assert snap["total"] == 46
    async with api.sessions() as session:
        await session.execute(update(User).where(User.id == "admin").values(role="user"))
        # No run references this media, so ownership can change independently.
        await session.execute(update(MediaFile).where(MediaFile.id == "media-44").values(user_id="admin"))
        await session.commit()
    result = (await search(api, result_set_id=snap["result_set_id"], size=100)).json()["data"]
    assert result["total"] == 1 and result["results"][0]["media_id"] == "media-44"
    api.client.headers["Authorization"] = "Bearer owner"
    assert (await search(api, result_set_id=snap["result_set_id"])).status_code == 404


async def test_admin_can_read_other_snapshot(api):
    snap = await snapshot(api)
    api.client.headers["Authorization"] = "Bearer admin"
    assert (await api.client.get(f"{PREFIX}/result-sets/{snap['result_set_id']}")).status_code == 200
    assert (await search(api, result_set_id=snap["result_set_id"])).json()["data"]["total"] == 45


async def test_snapshot_10000_accepted_10001_rejected_without_partial_write(api):
    async with api.sessions() as session:
        media = [{
            "id": f"bulk-{index}", "user_id": "owner",
            "tos_url": f"tos://owner-bucket/bulk/{index}.png", "file_type": "image",
            "file_name": f"{index}.png", "created_at": NOW,
        } for index in range(9955)]
        await session.execute(insert(MediaFile), media)
        await session.execute(insert(MediaTag), [{
            "user_id": "owner", "media_id": item["id"], "source": "default",
            "category": "road", "tag_name": "highway",
        } for item in media])
        await session.commit()
    snap = await snapshot(api)
    assert snap["total"] == 10000
    async with api.sessions() as session:
        session.add(MediaFile(
            id="too-many", user_id="owner", tos_url="tos://owner-bucket/too-many.png",
            file_name="too-many.png", file_type="image",
        ))
        session.add(MediaTag(
            user_id="owner", media_id="too-many", source="default", category="road", tag_name="highway",
        ))
        await session.commit()
    response = await api.client.post(f"{PREFIX}/result-sets", json=SOURCE)
    assert response.status_code == 422
    assert "10000" in response.json()["message"] and "narrow" in response.json()["message"]
    async with api.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AnnotationResultSet)) == 1
        assert await session.scalar(select(func.count()).select_from(AnnotationResultSetMember)) == 10000


async def test_errors_never_leak_prompt_or_signed_url(api):
    api.sign.side_effect = RuntimeError("PRIVATE https://private/?Signature=SECRET")
    response = await api.client.get(f"{PREFIX}/media/media-00/preview")
    assert response.status_code == 503
    assert "PRIVATE" not in response.text and "SECRET" not in response.text
    api.jobs.side_effect = ServiceError("ark", "not_configured")
    response = await api.client.post(f"{PREFIX}/jobs", json={"media_ids": ["media-00"]})
    assert response.status_code == 503
    response = await api.client.post(f"{PREFIX}/jobs", json={
        "media_ids": ["media-00"], "options": {
            "annotation_mode": "custom", "custom_annotation_prompt": "SECRET" * 2000,
        },
    })
    assert response.status_code == 422
    assert "SECRET" not in response.text and "ctx" not in response.text


def test_exact_identity_compiles_portably():
    expression = exact_text(MediaFile.file_name, "Case.png")
    assert "AS BINARY" in str(expression.compile(dialect=mysql.dialect()))
    assert "AS BLOB" in str(expression.compile(dialect=sqlite.dialect()))


async def test_config_without_owner_credentials_and_no_cloud_calls(api):
    async with api.sessions() as session:
        await session.execute(delete(UserSystemSettings))
        await session.commit()
    response = await api.client.get(f"{PREFIX}/config")
    assert response.status_code == 200
    config = response.json()["data"]
    assert config["default_prompt"]
    assert config["model"] == "doubao-seed-2-1-lite-260915"
    assert config["limits"]["max_result_set_members"] == 10000
    assert config["limits"]["result_set_ttl_seconds"] == 86400
    assert config["defaults"]["generate_annotations"] is True
    api.sign.assert_not_awaited()
    api.jobs.assert_not_awaited()


@pytest.mark.parametrize("pointer", ["published", "foreign-run"])
async def test_corrupt_published_pointer_never_returns_other_media_run(api, pointer):
    async with api.sessions() as session:
        await session.execute(update(MediaFile).where(MediaFile.id == "media-01").values(
            published_annotation_run_id=pointer,
        ))
        await session.commit()
    for owner in ("owner", "admin"):
        api.client.headers["Authorization"] = f"Bearer {owner}"
        detail = (await api.client.get(f"{PREFIX}/media/media-01")).json()["data"]
        assert detail["published_run"] is None
        assert detail["media"]["published_run_id"] is None
        result = (await search(api, filenames="same.png")).json()["data"]
        row = next(item for item in result["results"] if item["media_id"] == "media-01")
        assert row["published_run_id"] is None and row["object_count"] == 0


async def test_empty_snapshot_never_expands_to_all_media(api):
    snap = await snapshot(api, {"tags": [{**SOURCE["tags"][0], "name": "missing"}]})
    assert snap["total"] == 0
    result = (await search(api, result_set_id=snap["result_set_id"])).json()["data"]
    assert result["total"] == 0 and result["results"] == []


@pytest.mark.parametrize("body", [
    {"tags": []}, {"tags": [{"category": "road", "name": "highway"}]},
    {**SOURCE, "logic": "XOR"}, {**SOURCE, "page": 1},
])
async def test_snapshot_rejects_missing_source_pagination_and_invalid_logic(api, body):
    response = await api.client.post(f"{PREFIX}/result-sets", json=body)
    assert response.status_code == 422


async def test_job_retry_options_and_batch_limits(api):
    for body in [
        {"media_ids": [], "action": "generate"},
        {"media_ids": ["media-00"] * 101},
        {"media_ids": ["media-00"], "action": "retry", "options": {}},
    ]:
        response = await api.client.post(f"{PREFIX}/jobs", json=body)
        assert response.status_code == 422
    api.jobs.assert_not_awaited()


async def test_absent_job_service_fails_closed(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(annotations_router, "import_module", missing)
    with pytest.raises(ServiceError) as error:
        await annotations_router.submit_annotation_job(session=None, user_id="owner", request=None)
    assert error.value.status_code == 503


async def test_actual_job_adapter_forwards_only_owner_and_schema(monkeypatch):
    submit = AsyncMock(return_value={"status": "pending"})
    monkeypatch.setattr(
        annotations_router, "import_module",
        lambda name: SimpleNamespace(annotation_job_service=SimpleNamespace(submit_job=submit)),
    )
    request = object()
    result = await annotations_router.submit_annotation_job(session=None, user_id="owner", request=request)
    assert result == {"status": "pending"}
    submit.assert_awaited_once_with(session=None, user_id="owner", request=request)


async def test_anonymous_bad_json_is_401_before_validation_or_database(api):
    api.client.headers.pop("Authorization")

    async def unavailable_session():
        raise AssertionError("Anonymous request must not open a database session")
        yield

    api.app.dependency_overrides[get_session] = unavailable_session
    response = await api.client.post(f"{PREFIX}/search", content=b"{bad-json")
    assert response.status_code == 401
    assert response.json()["code"] == 401
    assert (await api.client.get(f"{PREFIX}/frames/frame-00/image?token=owner")).status_code == 401


async def test_admin_can_submit_only_own_resource(api):
    api.client.headers["Authorization"] = "Bearer admin"
    async with api.sessions() as session:
        await session.execute(update(MediaFile).where(MediaFile.id == "media-01").values(user_id="admin"))
        await session.commit()
    api.jobs.return_value = {
        "task_id": "task-1", "status": "pending", "media_ids": ["media-01"], "run_ids": ["run-1"],
    }
    response = await api.client.post(f"{PREFIX}/jobs", json={"media_ids": ["media-01"]})
    assert response.status_code == 200
    assert api.jobs.call_args.kwargs["user_id"] == "admin"


async def test_missing_storage_config_fails_without_cloud_calls(api, monkeypatch):
    monkeypatch.setattr(query_module, "settings", query_module.settings.model_copy(update={
        "ANNOTATION_STORAGE_DIR": "", "ANNOTATION_TEMP_DIR": "",
    }))
    response = await api.client.get(f"{PREFIX}/frames/frame-00/image")
    assert response.status_code == 503
    assert response.json()["data"]["category"] == "not_configured"
    api.sign.assert_not_awaited()


async def test_router_respects_explicit_auth_dependency_override(api):
    api.client.headers.pop("Authorization")
    api.app.dependency_overrides[deps.get_current_user] = lambda: {"id": "owner", "role": "user"}
    response = await api.client.post(f"{PREFIX}/jobs", json={
        "media_ids": ["media-00"], "action": "retry", "options": {},
    })
    assert response.status_code == 422
    api.jobs.assert_not_awaited()
