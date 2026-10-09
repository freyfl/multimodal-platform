"""Offline T4 orchestration: real SQLite checkpoints, mocked paid/cloud calls."""

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from PIL import Image
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import import_router
from app.api.deps import get_current_user, get_user_settings
from app.errors import MissingConfigurationError, ServiceError
from app.main import app
from app.models import database
from app.models.annotation_schemas import ANNOTATION_MODEL, AnnotationJobRequest
from app.models.models import AnnotationFrame, AnnotationRun, ImportTask, MediaFile, UserSystemSettings
from app.models.schemas import ImportStartRequest
from app.services import annotation_job_service as module
from app.services.annotation_frame_service import PreparedFrame, PreparedFrames


CONFIG = {
    "ark_api_key": "private-owner-key", "tag_model": ANNOTATION_MODEL,
    "tos_bucket_name": "bucket", "tos_access_key_id": "private-ak",
    "tos_access_key_secret": "private-sk", "tos_endpoint": "https://tos.invalid",
    "tos_region": "cn-beijing",
}
FILE = {
    "tos_url": "tos://bucket/road.jpg", "file_name": "road.jpg",
    "file_size": 42, "file_type": "image",
}


@pytest.fixture
async def jobs(tmp_path, monkeypatch, empty_settings):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", sessions)
    empty_settings.ANNOTATION_STORAGE_DIR = str(tmp_path / "frames")
    empty_settings.ANNOTATION_TEMP_DIR = str(tmp_path / "temporary")
    empty_settings.ARK_MAX_CONCURRENCY = 1
    monkeypatch.setattr(module, "settings", empty_settings)
    monkeypatch.setattr(import_router, "settings", empty_settings)
    service = module.AnnotationJobService()
    service.prepare()
    import_router.prepare_import_tasks()
    monkeypatch.setattr(module, "annotation_job_service", service)
    monkeypatch.setattr(import_router, "annotation_job_service", service)
    await database.init_db()
    async with sessions() as session:
        session.add_all([
            UserSystemSettings(user_id="owner", **CONFIG),
            MediaFile(id="media", user_id="owner", **FILE, tag_status="done", vector_status="done"),
            MediaFile(id="foreign", user_id="other", **{**FILE, "tos_url": "tos://bucket/other.jpg"}),
        ])
        await session.commit()
    state = SimpleNamespace(etag="v1", version="1", frames=3, heads=[])

    async def open_object(uri, method):
        state.heads.append((uri, method))
        return SimpleNamespace(
            status_code=200,
            headers={"ETag": state.etag, "x-tos-version-id": state.version},
            aclose=AsyncMock(),
        )

    tos = SimpleNamespace(
        open_object=AsyncMock(side_effect=open_object),
        list_files=AsyncMock(return_value=[FILE]),
        get_file_url=AsyncMock(return_value="https://tos.invalid/road.jpg?private-signature=1"),
    )

    @asynccontextmanager
    async def borrow(config):
        assert config["ark_api_key"] == CONFIG["ark_api_key"]
        yield tos

    monkeypatch.setattr(module, "borrow_tos", borrow)
    monkeypatch.setattr(import_router, "borrow_tos", borrow)

    async def prepare(media, config, *, context, **kwargs):
        frames = []
        for index in range(state.frames):
            identity = uuid4().hex
            key = f"{context.user_id}/{context.media_id}/{context.revision}/{identity}.png"
            path = context.storage_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 6)).save(path)
            frames.append(PreparedFrame(identity, index, index * 1000, 8, 6, key, path))
        return PreparedFrames(frames, state.frames, state.etag, state.version)

    frames = SimpleNamespace(
        prepare_frames=AsyncMock(side_effect=prepare),
        resolve_frame_path=module.annotation_frame_service.resolve_frame_path,
        cleanup_temporary=module.annotation_frame_service.cleanup_temporary,
    )
    inference = SimpleNamespace(annotate_frame=AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "annotation_frame_service", frames)
    monkeypatch.setattr(module, "annotation_service", inference)
    tags = SimpleNamespace(generate_tags=AsyncMock(return_value=[]))
    vectors = SimpleNamespace(embed_media=AsyncMock(return_value=[1.0] * 1024))
    milvus = SimpleNamespace(ensure_collection=AsyncMock(), upsert=AsyncMock(return_value="vector"))
    monkeypatch.setattr(import_router, "tag_service", tags)
    monkeypatch.setattr(import_router, "embedding_service", vectors)
    monkeypatch.setattr(import_router, "milvus_service", milvus)
    monkeypatch.setattr(app, "dependency_overrides", {
        get_current_user: lambda: {"id": "owner", "role": "user"},
        get_user_settings: lambda: dict(CONFIG),
        database.get_session: database.get_session,
    })
    fixture = SimpleNamespace(
        service=service, sessions=sessions, state=state, inference=inference,
        frames=frames, tos=tos, tags=tags, vectors=vectors, settings=empty_settings,
    )
    yield fixture
    await import_router.shutdown_import_tasks()
    await service.shutdown()
    await database.close_db()


async def submit(jobs, action="generate", **kwargs):
    async with jobs.sessions() as session:
        return await jobs.service.submit_job(
            session=session, user_id="owner",
            request=AnnotationJobRequest(media_ids=["media"], action=action, **kwargs),
        )


async def wait(jobs, response):
    worker = jobs.service.workers.get(response.task_id)
    if worker:
        await asyncio.wait_for(asyncio.shield(worker), 5)
    async with jobs.sessions() as session:
        return await session.scalar(select(ImportTask).where(ImportTask.task_id == response.task_id))


async def test_generate_reuse_force_and_snapshot(jobs):
    first = await submit(jobs, options={"annotation_mode": "custom", "custom_annotation_prompt": "private-prompt"})
    task = await wait(jobs, first)
    assert (task.status, task.annotation_status) == ("completed", "completed")
    assert (task.annotation_planned_frames, task.annotation_completed_frames) == (3, 3)
    async with jobs.sessions() as session:
        run = await session.get(AnnotationRun, first.run_ids[0])
        assert run.active_key is None
        assert (run.source_etag, run.source_version) == ("v1", "1")
        assert "private-prompt" in run.snapshot["prompt"]
        assert "private-owner-key" not in json.dumps(run.snapshot)
        assert (await session.get(MediaFile, "media")).published_annotation_run_id == run.id
        detail = import_router._task_detail(task).model_dump(mode="json")
        assert detail["annotation_progress"]["completed_frames"] == 3
        assert detail["generate_annotations"] is True
        assert detail["annotation_mode"] == "custom"
        assert detail["annotation_box_mode"] == "2d"
        assert detail["annotation_sample_interval_seconds"] == 1
        assert detail["annotation_max_frames"] == 60
        assert "private-" not in json.dumps(detail)
    second = await submit(jobs, options={"annotation_mode": "custom", "custom_annotation_prompt": "private-prompt"})
    await wait(jobs, second)
    assert second.run_ids == first.run_ids
    assert jobs.inference.annotate_frame.await_count == 3
    forced = await submit(jobs, "regenerate")
    await wait(jobs, forced)
    assert forced.run_ids != first.run_ids
    async with jobs.sessions() as session:
        assert (await session.get(AnnotationRun, forced.run_ids[0])).revision == 2
    jobs.tags.generate_tags.assert_not_awaited()
    jobs.vectors.embed_media.assert_not_awaited()


async def test_partial_preserves_published_then_retry_only_failed_frame(jobs):
    original = await submit(jobs)
    await wait(jobs, original)
    jobs.inference.annotate_frame.reset_mock()
    jobs.inference.annotate_frame.side_effect = [[], RuntimeError("private-prompt"), []]
    partial = await submit(jobs, "regenerate")
    task = await wait(jobs, partial)
    assert (task.status, task.annotation_status, task.failed_files) == ("failed", "partial", 1)
    async with jobs.sessions() as session:
        assert (await session.get(MediaFile, "media")).published_annotation_run_id == original.run_ids[0]
        run = await session.get(AnnotationRun, partial.run_ids[0])
        assert (run.completed_frames, run.failed_frames, run.active_key) == (2, 1, None)
        before = (await session.scalars(select(AnnotationFrame).where(
            AnnotationFrame.run_id == run.id, AnnotationFrame.status == "completed",
        ).order_by(AnnotationFrame.frame_index))).all()
        assert await jobs.service.retry_media_ids(session, task) == ["media"]
    jobs.inference.annotate_frame.side_effect = None
    jobs.inference.annotate_frame.reset_mock()
    retried = await submit(jobs, "retry")
    task = await wait(jobs, retried)
    assert retried.run_ids == partial.run_ids
    assert task.status == "completed"
    assert jobs.inference.annotate_frame.await_count == 1
    assert jobs.inference.annotate_frame.await_args.args[0].frame_index == 1
    assert jobs.frames.prepare_frames.await_count == 2
    async with jobs.sessions() as session:
        assert (await session.get(MediaFile, "media")).published_annotation_run_id == retried.run_ids[0]
        for prior in before:
            current = await session.get(AnnotationFrame, prior.id)
            assert current.updated_at == prior.updated_at
        old_task = await session.scalar(select(ImportTask).where(ImportTask.task_id == partial.task_id))
        assert await jobs.service.retry_media_ids(session, old_task) == []
    jobs.tags.generate_tags.assert_not_awaited()
    jobs.vectors.embed_media.assert_not_awaited()


async def test_retry_rejects_modified_source_and_new_options(jobs):
    jobs.inference.annotate_frame.side_effect = RuntimeError("private")
    response = await submit(jobs)
    await wait(jobs, response)
    count = jobs.inference.annotate_frame.await_count
    jobs.state.etag = "v2"
    with pytest.raises(ServiceError) as caught:
        await submit(jobs, "retry")
    assert caught.value.status_code == 409
    assert jobs.inference.annotate_frame.await_count == count
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test",
        headers={"Authorization": "Bearer offline"},
    ) as client:
        invalid = await client.post("/api/annotations/jobs", json={
            "media_ids": ["media"], "action": "retry",
            "options": {"annotation_mode": "custom", "custom_annotation_prompt": "private-prompt"},
        })
    assert invalid.status_code == 422
    assert "private-prompt" not in invalid.text


async def test_retry_rejects_legacy_model_snapshot(jobs):
    jobs.inference.annotate_frame.side_effect = RuntimeError("private")
    response = await submit(jobs)
    await wait(jobs, response)
    calls = jobs.inference.annotate_frame.await_count
    async with jobs.sessions() as session:
        run = await session.get(AnnotationRun, response.run_ids[0])
        run.snapshot = {
            **run.snapshot,
            "model": "doubao-seed-2-1-pro-260915",
        }
        await session.commit()
        task = await session.scalar(select(ImportTask).where(
            ImportTask.task_id == response.task_id,
        ))
        assert await jobs.service.retry_media_ids(session, task) == []
    with pytest.raises(ServiceError) as caught:
        await submit(jobs, "retry")
    assert caught.value.status_code == 409
    assert jobs.inference.annotate_frame.await_count == calls


async def test_concurrent_duplicate_reuses_active_task_and_visible_progress(jobs):
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        await release.wait()
        return []

    jobs.inference.annotate_frame.side_effect = block
    first = await submit(jobs)
    await asyncio.wait_for(entered.wait(), 3)
    duplicate = await submit(jobs)
    assert duplicate.task_id == first.task_id
    assert duplicate.run_ids == first.run_ids
    await asyncio.sleep(1.05)
    async with jobs.sessions() as session:
        task = await session.scalar(select(ImportTask))
        progress = import_router._task_detail(task).annotation_progress
        assert progress.current_media_id == "media"
        assert progress.current_frame_index == 0
        assert progress.planned_frames == 3
        assert task.annotation_elapsed_ms >= 900
    release.set()
    await wait(jobs, first)
    assert jobs.inference.annotate_frame.await_count == 3


async def test_frames_use_configured_concurrency_and_persist_all_checkpoints(jobs):
    jobs.settings.ARK_MAX_CONCURRENCY = 2
    active = peak = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def block(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if peak == 2:
            entered.set()
        await release.wait()
        active -= 1
        return []

    jobs.inference.annotate_frame.side_effect = block
    response = await submit(jobs)
    await asyncio.wait_for(entered.wait(), 3)
    assert jobs.inference.annotate_frame.await_count == 2
    release.set()
    task = await wait(jobs, response)
    assert peak == 2
    assert (task.status, task.annotation_status) == ("completed", "completed")
    async with jobs.sessions() as session:
        run = await session.get(AnnotationRun, response.run_ids[0])
        assert (run.planned_frames, run.processed_frames, run.completed_frames) == (3, 3, 3)


async def test_cancel_stops_later_requests_and_retry_keeps_finished_frame(jobs):
    entered = asyncio.Event()

    async def block(frame, *args, **kwargs):
        if frame.frame_index == 1:
            entered.set()
            await asyncio.Event().wait()
        return []

    jobs.inference.annotate_frame.side_effect = block
    response = await submit(jobs)
    await asyncio.wait_for(entered.wait(), 3)
    async with jobs.sessions() as session:
        await import_router.cancel_task(response.task_id, {"id": "owner"}, session)
    assert jobs.inference.annotate_frame.await_count == 2
    async with jobs.sessions() as session:
        task = await session.scalar(select(ImportTask))
        run = await session.get(AnnotationRun, response.run_ids[0])
        assert (task.status, task.annotation_status, run.status) == ("cancelled", "cancelled", "cancelled")
        assert run.completed_frames == 1 and run.active_key is None
    jobs.inference.annotate_frame.side_effect = None
    jobs.inference.annotate_frame.reset_mock()
    retried = await submit(jobs, "retry")
    assert (await wait(jobs, retried)).status == "completed"
    assert jobs.inference.annotate_frame.await_count == 2


async def test_recovery_never_schedules_paid_requests(jobs):
    response = await submit(jobs)
    await wait(jobs, response)
    async with jobs.sessions() as session:
        run = await session.get(AnnotationRun, response.run_ids[0])
        run.status, run.active_key = "running", run.idempotency_hash
        task = await session.scalar(select(ImportTask))
        task.status, task.annotation_status = "running", "running"
        await session.commit()
    calls = jobs.inference.annotate_frame.await_count
    await jobs.service.recover()
    assert jobs.inference.annotate_frame.await_count == calls
    async with jobs.sessions() as session:
        run = await session.get(AnnotationRun, response.run_ids[0])
        assert run.status == "partial" and run.active_key is None
        assert (await session.scalar(select(ImportTask))).status == "failed"


@pytest.mark.parametrize("user_id,media_ids", [
    ("owner", ["foreign"]), ("owner", ["media", "foreign"]), ("other", ["media"]),
])
async def test_jobs_owner_check_precedes_cloud(jobs, user_id, media_ids):
    async with jobs.sessions() as session:
        with pytest.raises(ServiceError) as caught:
            await jobs.service.submit_job(
                session=session, user_id=user_id, request=AnnotationJobRequest(media_ids=media_ids),
            )
        assert caught.value.status_code == 404
    jobs.tos.open_object.assert_not_awaited()


async def test_missing_owner_credentials_never_fall_back(jobs):
    jobs.settings.ARK_API_KEY = "deployment-secret"
    async with jobs.sessions() as session:
        owner = await session.scalar(select(UserSystemSettings))
        owner.ark_api_key = None
        await session.commit()
    with pytest.raises(MissingConfigurationError):
        await submit(jobs)
    jobs.tos.open_object.assert_not_awaited()


@pytest.mark.parametrize("transport", ["json", "multipart"])
@pytest.mark.parametrize("vectors,tags,annotations", [
    (False, False, True), (False, True, False), (True, False, False),
    (True, True, True), (False, False, False),
])
async def test_import_stage_options_and_transports(jobs, transport, vectors, tags, annotations):
    payload = {
        "tos_directory": "tos://bucket/", "generate_vectors": vectors,
        "generate_tags": tags, "generate_annotations": annotations,
    }
    if not annotations:
        payload.update(annotation_mode="custom", custom_annotation_prompt=" ")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        if transport == "json":
            result = await client.post("/api/import/start", json=payload)
        else:
            result = await client.post("/api/import/start", files={
                key: (None, str(value).lower() if isinstance(value, bool) else str(value))
                for key, value in payload.items()
            })
        assert result.status_code == 200, result.text
        task_id = result.json()["data"]["task_id"]
        worker = import_router._tasks.get(task_id)
        if worker:
            await asyncio.wait_for(asyncio.shield(worker), 5)
        detail = (await client.get(f"/api/import/tasks/{task_id}")).json()["data"]
    assert detail["status"] == "completed", detail
    assert detail["annotation_status"] == ("completed" if annotations else "skipped")
    assert detail["generate_annotations"] is annotations
    assert detail["annotation_mode"] == ("default" if annotations else None)
    assert detail["annotation_box_mode"] == ("2d" if annotations else None)
    assert detail["annotation_sample_interval_seconds"] == (1 if annotations else None)
    assert detail["annotation_max_frames"] == (60 if annotations else None)
    assert jobs.tags.generate_tags.await_count == int(tags)
    assert jobs.vectors.embed_media.await_count == int(vectors)
    assert jobs.inference.annotate_frame.await_count == (3 if annotations else 0)


async def test_import_annotation_failure_retains_tags_vectors_and_retry_is_annotation_only(jobs):
    jobs.inference.annotate_frame.side_effect = [[], RuntimeError("private-prompt"), []]
    async with jobs.sessions() as session:
        response = await import_router.start_import(
            ImportStartRequest(tos_directory="tos://bucket/"),
            {"id": "owner"}, dict(CONFIG), session,
        )
    worker = import_router._tasks[response.data["task_id"]]
    await asyncio.wait_for(asyncio.shield(worker), 5)
    async with jobs.sessions() as session:
        task = await session.scalar(select(ImportTask))
        assert task.status == "failed" and task.annotation_status == "partial"
        media = await session.get(MediaFile, "media")
        assert (media.tag_status, media.vector_status, media.annotation_status) == ("done", "done", "partial")
    jobs.inference.annotate_frame.side_effect = None
    retry = await submit(jobs, "retry")
    assert (await wait(jobs, retry)).status == "completed"
    assert jobs.tags.generate_tags.await_count == 1
    assert jobs.vectors.embed_media.await_count == 1


async def test_timeout_releases_run_and_task(jobs):
    jobs.settings.TASK_TIMEOUT = 0.15

    async def block(*args, **kwargs):
        await asyncio.Event().wait()

    jobs.inference.annotate_frame.side_effect = block
    response = await submit(jobs)
    task = await wait(jobs, response)
    assert task.status == "failed"
    async with jobs.sessions() as session:
        run = await session.get(AnnotationRun, response.run_ids[0])
        assert run.active_key is None and run.status not in module.ACTIVE


async def test_legacy_task_response_is_not_started(jobs):
    async with jobs.sessions() as session:
        task = ImportTask(user_id="owner", task_id="legacy", tos_directory="tos://bucket/")
        session.add(task)
        await session.commit()
        detail = import_router._task_detail(task)
    assert detail.annotation_status == "not_started"
    assert detail.annotation_progress.planned_frames == 0
    assert detail.annotation_retry_media_ids == []
    assert detail.generate_annotations is None
    assert detail.annotation_mode is None
