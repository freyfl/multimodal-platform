"""Independent offline acceptance: real SQL transactions, fake cloud boundaries.

Only disposable SQLite/private-frame fixtures are used. These tests do not
import implementation-owned tests, read dotenv, or invoke paid services.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.errors import ServiceError
from app.models.annotation_schemas import (
    ANNOTATION_MODEL, AnnotationJobRequest, AnnotationOptions,
)
from app.models.migrations import apply_migrations
from app.models.models import (
    AnnotationFrame, AnnotationRun, ImportTask, MediaFile, MediaTag,
    UserSystemSettings,
)
from app.services import annotation_job_service as jobs_module
from app.services import annotation_frame_service as frames_module
from app.services.annotation_frame_service import (
    AnnotationFrameService, FrameStorageContext, PreparedFrame, PreparedFrames,
)
from app.services.annotation_rules import build_rule_snapshot, parse_annotation_response


@pytest.fixture
async def acceptance(tmp_path, monkeypatch, empty_settings):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'acceptance.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(apply_migrations)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    config = empty_settings.model_copy(update={
        "ANNOTATION_STORAGE_DIR": str(tmp_path / "frames"),
        "ANNOTATION_TEMP_DIR": str(tmp_path / "temporary"),
        "ARK_MAX_CONCURRENCY": 1,
    })
    monkeypatch.setattr(jobs_module, "settings", config)
    monkeypatch.setattr(frames_module, "settings", config)
    monkeypatch.setattr(jobs_module, "async_session_maker", sessions)
    async with sessions() as session:
        session.add_all([
            MediaFile(
                id=owner, user_id=owner, file_name=f"{owner}.mp4",
                tos_url=f"tos://{owner}-bucket/input.mp4", file_type="video",
                tag_status="done", vector_status="done", vector_id=f"vector-{owner}",
                vector_collection="media_vectors_v2",
            ) for owner in ("owner", "other")
        ])
        session.add(UserSystemSettings(
            user_id="owner", ark_api_key="offline-owner-key", tag_model=ANNOTATION_MODEL,
            tos_bucket_name="owner-bucket",
        ))
        session.add(MediaTag(
            media_id="owner", user_id="owner", source="custom", category="road",
            tag_name="preserved", is_manual=1,
        ))
        await session.commit()

    prepared_calls = []

    async def prepare(media, user_config, *, context, **kwargs):
        prepared_calls.append(context)
        frames = []
        for index in range(3):
            identity = uuid4().hex
            key = f"{context.user_id}/{context.media_id}/{context.revision}/{identity}.png"
            path = context.storage_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            with Image.new("RGB", (20, 10), color="blue") as image:
                image.save(path)
            frames.append(PreparedFrame(identity, index, index * 1001.5, 20, 10, key, path))
        return PreparedFrames(frames, 3, context.source_etag, context.source_version)

    generator = AsyncMock(return_value=[])
    monkeypatch.setattr(jobs_module, "annotation_frame_service", SimpleNamespace(
        prepare_frames=AsyncMock(side_effect=prepare),
        resolve_frame_path=AnnotationFrameService.resolve_frame_path,
    ))
    monkeypatch.setattr(jobs_module, "annotation_service", SimpleNamespace(annotate_frame=generator))
    service = jobs_module.AnnotationJobService()
    service.prepare()
    head = AsyncMock(return_value=('"A"', "version-A"))
    monkeypatch.setattr(service, "head_source", head)
    state = SimpleNamespace(
        engine=engine, sessions=sessions, service=service, generator=generator,
        head=head, prepared_calls=prepared_calls, config=config,
    )
    try:
        yield state
    finally:
        for worker in tuple(service.workers.values()):
            worker.cancel()
        await asyncio.gather(*tuple(service.workers.values()), return_exceptions=True)
        await engine.dispose()


async def submit(state, *, action="generate", options=None, media_ids=None, user_id="owner"):
    request = AnnotationJobRequest(
        media_ids=media_ids or ["owner"], action=action, options=options,
    )
    async with state.sessions() as session:
        return await state.service.submit_job(session=session, user_id=user_id, request=request)


async def finish(state, response):
    worker = state.service.workers.get(response.task_id)
    if worker:
        await asyncio.wait_for(worker, timeout=10)
    async with state.sessions() as session:
        task = await session.scalar(select(ImportTask).where(ImportTask.task_id == response.task_id))
        run = await session.get(AnnotationRun, response.run_ids[0])
        media = await session.get(MediaFile, "owner")
        frames = (await session.scalars(select(AnnotationFrame).where(
            AnnotationFrame.run_id == run.id,
        ).order_by(AnnotationFrame.frame_index))).all()
        return task, run, media, frames


async def test_acceptance_partial_resume_reuses_success_and_publishes_atomically(acceptance):
    state = acceptance
    original = await submit(state)
    _, old_run, _, _ = await finish(state, original)
    assert old_run.status == "completed"
    state.generator.reset_mock()
    state.generator.side_effect = [
        [], ServiceError("ark", "timeout", status_code=504), [],
    ]
    failed = await submit(state, action="regenerate")
    task, run, media, frames = await finish(state, failed)
    assert (task.status, run.status, run.active_key) == ("failed", "partial", None)
    assert (run.completed_frames, run.failed_frames, run.processed_frames) == (2, 1, 3)
    assert media.published_annotation_run_id == old_run.id
    preserved = [(frame.id, frame.objects) for frame in frames if frame.status == "completed"]
    state.generator.reset_mock(side_effect=True)
    state.generator.return_value = []
    retry = await submit(state, action="retry")
    task, retried, media, frames = await finish(state, retry)
    assert retried.id == run.id and retried.revision == 2
    assert state.generator.await_count == 1
    assert state.generator.call_args.args[0].frame_index == 1
    assert [(frame.id, frame.objects) for frame in frames if frame.frame_index != 1] == preserved
    assert (task.status, retried.status, retried.active_key) == ("completed", "completed", None)
    assert media.published_annotation_run_id == retried.id
    assert len(state.prepared_calls) == 2
    async with state.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(MediaTag)) == 1
        assert (media.tag_status, media.vector_status, media.vector_id) == ("done", "done", "vector-owner")


async def test_acceptance_concurrent_identical_jobs_share_task_and_active_key(acceptance):
    state = acceptance
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await release.wait()
        return []

    state.generator.side_effect = blocked
    first = await submit(state)
    await asyncio.wait_for(entered.wait(), 3)
    try:
        others = await asyncio.gather(*(submit(state) for _ in range(5)))
        assert all(item.task_id == first.task_id and item.run_ids == first.run_ids for item in others)
        async with state.sessions() as session:
            run = await session.get(AnnotationRun, first.run_ids[0])
            assert run.active_key == run.idempotency_hash
            assert await session.scalar(select(func.count()).select_from(ImportTask)) == 1
            assert await session.scalar(select(func.count()).select_from(AnnotationRun)) == 1
        with pytest.raises(ServiceError) as caught:
            await submit(state, action="regenerate")
        assert caught.value.status_code == 409
    finally:
        release.set()
    await finish(state, first)
    assert state.generator.await_count == 3
    reused = await submit(state)
    _, run, _, _ = await finish(state, reused)
    assert run.id == first.run_ids[0] and run.active_key is None
    assert state.generator.await_count == 3


async def test_acceptance_source_change_blocks_retry_and_creates_unmixed_revision(acceptance):
    state = acceptance
    state.head.side_effect = [('"A"', "version-A"), ('"A"', "version-A"), ('"B"', "version-B")]
    response = await submit(state)
    _, old, media, old_frames = await finish(state, response)
    assert old.status == "partial" and old.error == "invalid_request"
    assert media.published_annotation_run_id is None
    assert all(frame.status == "completed" for frame in old_frames)
    state.head.side_effect = None
    state.head.return_value = ('"B"', "version-B")
    with pytest.raises(ServiceError) as caught:
        await submit(state, action="retry")
    assert caught.value.status_code == 409
    assert state.generator.await_count == 3
    response = await submit(state)
    _, fresh, media, fresh_frames = await finish(state, response)
    assert fresh.revision == old.revision + 1
    assert (fresh.source_etag, fresh.source_version) == ('"B"', "version-B")
    assert fresh.idempotency_hash != old.idempotency_hash
    assert {f.id for f in fresh_frames}.isdisjoint(f.id for f in old_frames)
    assert media.published_annotation_run_id == fresh.id


async def test_acceptance_cancel_preserves_first_frame_and_retry_skips_it(acceptance):
    state = acceptance
    second_started = asyncio.Event()

    async def stop_second(frame, *args, **kwargs):
        if frame.frame_index == 1:
            second_started.set()
            await asyncio.Event().wait()
        return []

    state.generator.side_effect = stop_second
    response = await submit(state)
    await asyncio.wait_for(second_started.wait(), 3)
    await state.service.cancel("owner", response.task_id)
    task, run, media, frames = await finish(state, response)
    assert task.status == run.status == "cancelled"
    assert frames[0].status == "completed" and run.active_key is None
    assert state.generator.await_count == 2
    assert media.published_annotation_run_id is None
    first_id = frames[0].id
    state.generator.reset_mock(side_effect=True)
    state.generator.return_value = []
    retry = await submit(state, action="retry")
    _, run, _, frames = await finish(state, retry)
    assert run.status == "completed" and frames[0].id == first_id
    assert [call.args[0].frame_index for call in state.generator.await_args_list] == [1, 2]


async def test_acceptance_restart_only_marks_retryable_never_schedules(acceptance):
    state = acceptance
    response = await submit(state)
    _, run, media, frames = await finish(state, response)
    async with state.sessions() as session:
        await session.execute(update(AnnotationRun).where(AnnotationRun.id == run.id).values(
            status="running", active_key=run.idempotency_hash,
        ))
        await session.execute(update(AnnotationFrame).where(AnnotationFrame.id == frames[-1].id).values(
            status="pending",
        ))
        await session.execute(update(ImportTask).where(ImportTask.task_id == response.task_id).values(
            status="running", annotation_status="running",
        ))
        await session.commit()
    state.generator.reset_mock()
    state.head.reset_mock()
    await state.service.recover()
    await state.service.recover()
    task, recovered, media, frames = await finish(state, response)
    assert recovered.status == "partial" and recovered.active_key is None
    assert task.status == "failed" and recovered.completed_frames == 2
    assert frames[0].status == frames[1].status == "completed"
    assert media.vector_collection == "media_vectors_v2"
    assert not state.service.workers
    state.generator.assert_not_awaited()
    state.head.assert_not_awaited()


async def test_acceptance_publication_sql_failure_rolls_back_entire_transaction(acceptance):
    state = acceptance
    first = await submit(state)
    _, old, _, _ = await finish(state, first)
    state.generator.side_effect = [[], ServiceError("ark", "timeout"), []]
    second = await submit(state, action="regenerate")
    _, replacement, _, _ = await finish(state, second)
    async with state.sessions() as session:
        await session.execute(update(AnnotationRun).where(AnnotationRun.id == replacement.id).values(
            status="running", active_key=replacement.idempotency_hash,
        ))
        await session.execute(update(ImportTask).where(ImportTask.task_id == second.task_id).values(status="running"))
        await session.execute(update(AnnotationFrame).where(AnnotationFrame.run_id == replacement.id).values(
            status="completed",
        ))
        await session.commit()

    def fail_publish(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE media_files") and "published_annotation_run_id=" in statement:
            raise RuntimeError("injected publish failure")

    event.listen(state.engine.sync_engine, "before_cursor_execute", fail_publish)
    try:
        with pytest.raises(RuntimeError, match="injected publish"):
            await state.service.terminal_run("owner", second.task_id, replacement.id)
    finally:
        event.remove(state.engine.sync_engine, "before_cursor_execute", fail_publish)
    async with state.sessions() as session:
        assert (await session.get(MediaFile, "owner")).published_annotation_run_id == old.id
        run = await session.get(AnnotationRun, replacement.id)
        assert run.status == "running" and run.active_key == replacement.idempotency_hash


@pytest.mark.parametrize("user_id,media_ids", [
    ("owner", ["owner", "other"]), ("admin", ["owner"]), ("other", ["owner"]),
])
async def test_acceptance_paid_boundary_owner_check_before_head(acceptance, user_id, media_ids):
    with pytest.raises(ServiceError) as caught:
        await submit(acceptance, user_id=user_id, media_ids=media_ids)
    assert caught.value.status_code == 404


@pytest.fixture
async def acceptance_api(acceptance, monkeypatch):
    from app import main
    from app.api import deps, import_router
    from app.models.database import get_session
    from app.services import annotation_query_service as query_module

    state = acceptance
    state.user = {"id": "owner", "role": "user"}
    owner_config = {
        "ark_api_key": "offline-owner-key", "tag_model": ANNOTATION_MODEL,
        "tos_bucket_name": "owner-bucket",
    }

    async def session_dependency():
        async with state.sessions() as session:
            yield session

    monkeypatch.setattr(main.app, "dependency_overrides", {
        deps.get_current_user: lambda: state.user,
        deps.get_user_settings: lambda: dict(owner_config),
        get_session: session_dependency,
    })
    monkeypatch.setattr(jobs_module, "annotation_job_service", state.service)
    monkeypatch.setattr(import_router, "annotation_job_service", state.service)
    monkeypatch.setattr(import_router, "async_session_maker", state.sessions)
    monkeypatch.setattr(import_router, "settings", state.config)
    monkeypatch.setattr(query_module, "settings", state.config)
    for name, value in {
        "_tasks": {}, "_media_locks": {}, "_registry_lock": asyncio.Lock(),
        "_limiter": asyncio.Semaphore(5), "_stopping": False,
    }.items():
        monkeypatch.setattr(import_router, name, value)
    state.imports = import_router
    state.tags = AsyncMock(return_value=[])
    state.vectors = AsyncMock(return_value=[0.0] * 1024)
    monkeypatch.setattr(import_router, "tag_service", SimpleNamespace(generate_tags=state.tags))
    monkeypatch.setattr(import_router, "embedding_service", SimpleNamespace(embed_media=state.vectors))
    monkeypatch.setattr(import_router, "milvus_service", SimpleNamespace(
        ensure_collection=AsyncMock(), upsert=AsyncMock(return_value="new-vector"),
    ))

    @asynccontextmanager
    async def borrow(config):
        yield SimpleNamespace(
            list_files=AsyncMock(return_value=[{
                "tos_url": "tos://owner-bucket/new.png", "file_name": "new.png",
                "file_type": "image", "file_size": 100,
            }]),
            get_file_url=AsyncMock(return_value="https://offline.invalid/mock"),
        )

    monkeypatch.setattr(import_router, "borrow_tos", borrow)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(main.app), base_url="http://offline.test",
    ) as client:
        state.client = client
        try:
            yield state
        finally:
            workers = tuple(import_router._tasks.values())
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)


async def test_acceptance_real_app_jobs_detail_and_frame_routes(acceptance_api):
    state = acceptance_api
    response = await state.client.post("/api/annotations/jobs", json={"media_ids": ["owner"]})
    assert response.status_code == 200, response.text
    from app.models.annotation_schemas import AnnotationJobResponse

    task_response = AnnotationJobResponse.model_validate(response.json()["data"])
    _, run, _, frames = await finish(state, task_response)
    detail = await state.client.get("/api/annotations/media/owner")
    assert detail.json()["data"]["published_run"]["id"] == run.id
    assert "prompt" not in detail.text and "objects" not in detail.text
    page = await state.client.get(f"/api/annotations/runs/{run.id}/frames?size=2&page=2")
    assert page.status_code == 200 and len(page.json()["data"]["results"]) == 1
    image = await state.client.get(f"/api/annotations/frames/{frames[0].id}/image")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    state.user = {"id": "other", "role": "user"}
    for path in [
        "/media/owner", f"/runs/{run.id}/frames", f"/frames/{frames[0].id}/image",
        "/media/owner/preview",
    ]:
        assert (await state.client.get("/api/annotations" + path)).status_code == 404
    state.user = {"id": "admin", "role": "admin"}
    assert (await state.client.get("/api/annotations/media/owner")).status_code == 200
    head_calls = state.head.await_count
    denied = await state.client.post("/api/annotations/jobs", json={"media_ids": ["owner"]})
    assert denied.status_code == 404 and state.head.await_count == head_calls


async def test_acceptance_snapshot_45_paged_immutable_expired_not_all(acceptance_api, monkeypatch):
    from app.services import annotation_query_service as query_module

    state = acceptance_api
    instant = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(query_module, "_now", lambda: instant)
    async with state.sessions() as session:
        for index in range(45):
            identity = f"snapshot-{index:02}"
            session.add(MediaFile(
                id=identity, user_id="owner", file_name="same.png",
                tos_url=f"tos://owner-bucket/{index}/same.png", file_type="image",
                created_at=instant.replace(tzinfo=None),
            ))
            session.add(MediaTag(
                user_id="owner", media_id=identity, source="custom", category="road",
                tag_name="snapshot-test",
            ))
        await session.commit()
    source = {"tags": [{"source": "custom", "category": "road", "name": "snapshot-test"}], "logic": "OR"}
    response = await state.client.post("/api/annotations/result-sets", json=source)
    assert response.status_code == 200, response.text
    snapshot = response.json()["data"]
    assert snapshot["source"] == source and snapshot["total"] == 45
    identity = snapshot["result_set_id"]
    ids = []
    for page, size in [(1, 12), (2, 12), (3, 12), (4, 9)]:
        response = await state.client.post("/api/annotations/search", json={
            "result_set_id": identity, "page": page, "size": 12,
        })
        result = response.json()["data"]
        assert result["total"] == 45 and len(result["results"]) == size
        ids.extend(item["media_id"] for item in result["results"])
    assert ids == [f"snapshot-{index:02}" for index in reversed(range(45))]
    async with state.sessions() as session:
        await session.execute(update(MediaTag).where(MediaTag.tag_name == "snapshot-test").values(
            tag_name="changed-after-snapshot",
        ))
        await session.execute(update(MediaFile).where(MediaFile.id == "snapshot-00").values(
            user_id="other",
        ))
        await session.commit()
    response = await state.client.post("/api/annotations/search", json={"result_set_id": identity})
    assert response.json()["data"]["total"] == 44
    assert (await state.client.get(f"/api/annotations/result-sets/{identity}")).json()["data"]["total"] == 45
    monkeypatch.setattr(query_module, "_now", lambda: instant + timedelta(hours=24))
    response = await state.client.post("/api/annotations/search", json={"result_set_id": identity})
    assert response.status_code == 410 and "results" not in response.json()["data"]
    state.user = {"id": "other", "role": "user"}
    assert (await state.client.get(f"/api/annotations/result-sets/{identity}")).status_code == 404


@pytest.mark.parametrize("transport", ["json", "multipart"])
@pytest.mark.parametrize("vectors,tags,annotations", [
    (False, False, None), (False, True, False), (True, False, False), (True, True, True),
])
async def test_acceptance_real_import_defaults_and_independent_stages(
    acceptance_api, transport, vectors, tags, annotations,
):
    state = acceptance_api
    payload = {
        "tos_directory": "tos://owner-bucket/", "generate_vectors": vectors,
        "generate_tags": tags,
    }
    if annotations is not None:
        payload["generate_annotations"] = annotations
    if annotations is False:
        payload.update(annotation_mode="custom", custom_annotation_prompt="")
    if transport == "json":
        response = await state.client.post("/api/import/start", json=payload)
    else:
        response = await state.client.post("/api/import/start", files={
            key: (None, str(value).lower() if isinstance(value, bool) else value)
            for key, value in payload.items()
        })
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["task_id"]
    worker = state.imports._tasks.get(task_id)
    if worker:
        await asyncio.wait_for(worker, 10)
    detail = (await state.client.get(f"/api/import/tasks/{task_id}")).json()["data"]
    assert detail["status"] == "completed"
    assert detail["annotation_status"] == ("skipped" if annotations is False else "completed")
    assert state.tags.await_count == int(tags)
    assert state.vectors.await_count == int(vectors)
    assert state.generator.await_count == (0 if annotations is False else 3)


async def test_acceptance_runtime_settings_consumed_by_frame_service(acceptance):
    config = acceptance.config.model_copy(update={
        "ANNOTATION_MAX_VIDEO_BYTES": 12345, "ANNOTATION_MAX_VIDEO_SECONDS": 20,
        "ANNOTATION_MAX_FRAME_PIXELS": 200, "ANNOTATION_DECODE_TIMEOUT": 7,
        "ANNOTATION_DECODE_CONCURRENCY": 1,
    })
    service = AnnotationFrameService(config=config)
    assert (service.max_video_bytes, service.max_duration_seconds, service.max_pixels) == (12345, 20, 200)
    assert service.subprocess_timeout == 7
    context = FrameStorageContext.from_settings("u", "m", "r", config=config)
    assert str(context.storage_dir) == config.ANNOTATION_STORAGE_DIR
    assert str(context.temp_dir) == config.ANNOTATION_TEMP_DIR
    with pytest.raises(ServiceError):
        service._dimensions(20, 11, video=True)
    acceptance.head.assert_not_awaited()
    acceptance.generator.assert_not_awaited()
    async with acceptance.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ImportTask)) == 0


async def test_acceptance_missing_owner_key_rejects_deployment_fallback(acceptance, monkeypatch):
    monkeypatch.setattr(jobs_module.settings, "ARK_API_KEY", "deployment-key-must-not-be-used")
    async with acceptance.sessions() as session:
        await session.execute(update(UserSystemSettings).values(ark_api_key=None))
        await session.commit()
    with pytest.raises(ServiceError) as caught:
        await submit(acceptance)
    assert caught.value.category == "not_configured"
    acceptance.head.assert_not_awaited()


async def test_acceptance_prompt_errors_sanitized_in_storage_and_actual_logger(acceptance, monkeypatch):
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = jobs_module.logger
    monkeypatch.setattr(logger, "handlers", [Capture()])
    sentinel = "PROMPT-PRIVATE-DO-NOT-LOG"
    acceptance.generator.side_effect = RuntimeError(
        sentinel + " https://private.invalid/image?Signature=private-signature"
    )
    response = await submit(acceptance, options=AnnotationOptions(
        annotation_mode="custom", custom_annotation_prompt=sentinel,
    ))
    task, run, _, frames = await finish(acceptance, response)
    assert task.status == run.status == "failed"
    assert all(frame.error == "unavailable" for frame in frames)
    assert sentinel not in str(records) and "private-signature" not in str(records)
    assert sentinel in run.snapshot["prompt"]
    assert sentinel not in str(task.error_message)
    future = asyncio.get_running_loop().create_future()
    future.set_exception(RuntimeError(sentinel))
    acceptance.service._finished("absent", future)
    assert records and sentinel not in str(records)


@pytest.mark.parametrize("source", ["source_etag", "source_version"])
def test_acceptance_source_hash_includes_each_version_component(source):
    params = dict(model=ANNOTATION_MODEL, source_etag='"A"', source_version="v1")
    first = build_rule_snapshot(AnnotationOptions(), **params)
    params[source] = "changed"
    assert first.rule_hash != build_rule_snapshot(AnnotationOptions(), **params).rule_hash
    assert parse_annotation_response('{"objects":[]}').objects == []


@pytest.mark.parametrize("failure", ["version_race", "short", "overflow", "redirect", "encoding"])
async def test_acceptance_download_bounds_and_head_get_version_consistency(tmp_path, failure):
    output = BytesIO()
    with Image.new("RGB", (10, 10)) as image:
        image.save(output, format="PNG")
    data = output.getvalue()
    streams, calls = [], []

    class Stream:
        def __init__(self, method):
            self.status_code = 302 if failure == "redirect" else 200
            self.headers = {"content-length": str(len(data)), "etag": '"A"', "x-tos-version-id": "v1"}
            self.closed = False
            if method == "GET":
                if failure == "version_race":
                    self.headers["x-tos-version-id"] = "v2"
                if failure == "encoding":
                    self.headers["content-encoding"] = "gzip"

        async def aiter_bytes(self):
            yield data[:-1] if failure == "short" else data
            if failure == "overflow":
                yield b"x"

        async def aclose(self):
            self.closed = True

    async def open_object(uri, *, method="GET"):
        calls.append((uri, method))
        stream = Stream(method)
        streams.append(stream)
        return stream

    @asynccontextmanager
    async def borrow(config):
        yield SimpleNamespace(open_object=open_object)

    context = FrameStorageContext(
        "owner", "media", "version", tmp_path / "frames", tmp_path / "temporary",
        source_etag='"A"', source_version="v1",
    )
    service = AnnotationFrameService(tos_borrower=borrow)
    media = dict(id="media", user_id="owner", tos_url="tos://bucket/a.png", file_type="image")
    with pytest.raises(ServiceError):
        await service.prepare_frames(media, {"tos_bucket_name": "bucket"}, context=context)
    assert all(stream.closed for stream in streams)
    assert not list(context.temp_dir.iterdir())
    assert not list(context.storage_dir.rglob("*.png"))
    assert all(uri == media["tos_url"] for uri, _ in calls)
    with pytest.raises(ServiceError) as caught:
        await service.prepare_frames(media, {"tos_bucket_name": "bucket"}, context=replace(context, user_id="other"))
    assert caught.value.status_code == 404
