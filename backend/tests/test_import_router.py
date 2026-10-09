"""Offline import orchestration tests with SQLite and injected cloud services."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import import_router
from app.models import database
from app.models.models import ImportTask, MediaFile, MediaTag
from app.models.schemas import ImportStartRequest
from app.services.tos_service import TOSService


FILE = {
    "tos_url": "tos://bucket/road.jpg",
    "file_name": "road.jpg",
    "file_size": 42,
    "file_type": "image",
}


@pytest.fixture
async def import_db(monkeypatch, empty_settings):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", sessions)
    monkeypatch.setattr(import_router, "settings", empty_settings)
    await database.init_db()
    import_router.prepare_import_tasks()
    yield sessions
    await import_router.shutdown_import_tasks()
    await database.close_db()


def cloud_services(monkeypatch, *, embedding=None, tags=None):
    tos = SimpleNamespace(
        list_files=AsyncMock(return_value=[FILE]),
        get_file_url=AsyncMock(return_value="https://tos.invalid/road.jpg?signed=1"),
        aclose=AsyncMock(),
    )
    embedding_service = SimpleNamespace(
        embed_media=AsyncMock(return_value=embedding or [1.0] + [0.0] * 1023),
    )
    tag_service = SimpleNamespace(generate_tags=AsyncMock(return_value=tags or []))
    milvus = SimpleNamespace(
        ensure_collection=AsyncMock(),
        upsert=AsyncMock(return_value="media-vector"),
    )
    monkeypatch.setattr(TOSService, "from_settings", lambda values: tos)
    monkeypatch.setattr(import_router, "embedding_service", embedding_service)
    monkeypatch.setattr(import_router, "tag_service", tag_service)
    monkeypatch.setattr(import_router, "milvus_service", milvus)
    return tos, embedding_service, tag_service, milvus


async def add_task(
    sessions, task_id, *, total=1, status="pending", processed=0, failed=0,
    tag_mode="default", custom_tag_prompt=None,
):
    async with sessions() as session:
        session.add(ImportTask(
            user_id="user-1", task_id=task_id,
            tos_directory="tos://bucket/", status=status,
            total_files=total, processed_files=processed, failed_files=failed,
            tag_mode=tag_mode, custom_tag_prompt=custom_tag_prompt,
        ))
        await session.commit()


async def test_retry_regenerates_with_task_snapshot_and_preserves_manual_tags(
    import_db, monkeypatch, empty_settings,
):
    sessions = import_db
    generated = [
        {"category": "road", "tag_name": "城市道路", "confidence": 0.7},
        {"category": "weather", "tag_name": "晴天", "confidence": 0.9},
    ]
    _, embedding, tags, milvus = cloud_services(monkeypatch, tags=generated)
    async with sessions() as session:
        media = MediaFile(
            user_id="user-1", tos_url=FILE["tos_url"],
            file_name="old.jpg", file_size=1,
            file_type="image", vector_status="done", vector_model="old-model",
            vector_dimension=1024, vector_instruction_version="old",
            vector_collection=empty_settings.MILVUS_COLLECTION, tag_status="failed",
        )
        session.add(media)
        await session.flush()
        session.add(MediaTag(
            user_id="user-1", media_id=media.id,
            category="road", tag_name="城市道路",
            confidence=1.0, is_manual=1,
        ))
        await session.commit()
        media_id = media.id

    await add_task(sessions, "first")
    await import_router.process_import_task("first", [FILE], "user-1", user_settings={})

    async with sessions() as session:
        task = await session.scalar(select(ImportTask).where(ImportTask.task_id == "first"))
        media = await session.get(MediaFile, media_id)
        saved_tags = (await session.scalars(
            select(MediaTag).where(MediaTag.media_id == media_id).order_by(MediaTag.category)
        )).all()
        assert (task.status, task.processed_files, task.failed_files) == ("completed", 1, 0)
        assert (media.file_name, media.file_size, media.vector_status, media.tag_status) == (
            "road.jpg", 42, "done", "done",
        )
        assert media.vector_model == empty_settings.ARK_EMBEDDING_MODEL
        assert [(tag.source, tag.category, tag.tag_name, tag.is_manual) for tag in saved_tags] == [
            ("default", "road", "城市道路", 1),
            ("default", "weather", "晴天", 0),
        ]

    prompt_snapshot = "只标注道路风险"
    await add_task(
        sessions, "retry", tag_mode="custom", custom_tag_prompt=prompt_snapshot,
    )
    await import_router.process_import_task("retry", [FILE], "user-1", user_settings={})
    assert embedding.embed_media.await_count == 1
    assert tags.generate_tags.await_count == 2
    assert tags.generate_tags.await_args.kwargs["tag_mode"] == "custom"
    assert tags.generate_tags.await_args.kwargs["custom_prompt"] == prompt_snapshot
    assert milvus.upsert.await_count == 1
    async with sessions() as session:
        assert await session.scalar(select(MediaFile).where(MediaFile.tos_url == FILE["tos_url"]))
        saved_tags = (await session.scalars(
            select(MediaTag).order_by(MediaTag.source, MediaTag.category)
        )).all()
        assert [
            (tag.source, tag.category, tag.tag_name, tag.is_manual)
            for tag in saved_tags
        ] == [
            ("custom", "road", "城市道路", 0),
            ("custom", "weather", "晴天", 0),
            ("default", "road", "城市道路", 1),
        ]


async def test_start_import_persists_tag_snapshot_without_passing_prompt_to_worker(
    import_db, monkeypatch,
):
    sessions = import_db
    cloud_services(monkeypatch)
    worker = AsyncMock()
    monkeypatch.setattr(import_router, "process_import_task", worker)
    request = ImportStartRequest(
        tos_directory="tos://bucket/",
        generate_annotations=False,
        tag_mode="custom",
        custom_tag_prompt="  snapshot prompt  ",
    )

    async with sessions() as session:
        response = await import_router.start_import(
            request,
            current_user={"id": "user-1", "role": "user"},
            user_settings={},
            session=session,
        )
    await asyncio.sleep(0)

    async with sessions() as session:
        task = await session.scalar(select(ImportTask))
        assert task.tag_mode == "custom"
        assert task.custom_tag_prompt == "snapshot prompt"
        detail = import_router._task_detail(task).model_dump()
        assert detail["tag_mode"] == "custom"
        assert detail["generate_annotations"] is False
        assert detail["annotation_mode"] is None
        assert detail["annotation_box_mode"] is None
        assert detail["annotation_sample_interval_seconds"] is None
        assert detail["annotation_max_frames"] is None
        assert "custom_tag_prompt" not in detail
    worker.assert_awaited_once()
    assert "snapshot prompt" not in repr(worker.await_args)
    assert response.data["task_id"] == task.task_id


async def test_generate_tags_false_skips_model_and_leaves_existing_tags(
    import_db, monkeypatch,
):
    sessions = import_db
    _, _, tags, _ = cloud_services(monkeypatch)
    async with sessions() as session:
        media = MediaFile(
            user_id="user-1", tos_url=FILE["tos_url"], file_name=FILE["file_name"],
            file_size=FILE["file_size"], file_type=FILE["file_type"],
            vector_status="skipped", tag_status="done",
        )
        session.add(media)
        await session.flush()
        session.add(MediaTag(
            user_id="user-1", media_id=media.id, source="custom",
            category="risk", tag_name="积水", confidence=0.8, is_manual=0,
        ))
        await session.commit()

    await add_task(sessions, "no-tags", tag_mode="custom")
    await import_router.process_import_task(
        "no-tags", [FILE], "user-1",
        generate_vectors=False, generate_tags=False, user_settings={},
    )

    tags.generate_tags.assert_not_awaited()
    async with sessions() as session:
        media = await session.scalar(select(MediaFile))
        saved = (await session.scalars(select(MediaTag))).all()
        assert media.tag_status == "done"
        assert [(tag.source, tag.tag_name) for tag in saved] == [("custom", "积水")]


async def test_stage_failure_marks_file_and_task_failed_but_finishes_other_stage(
    import_db, monkeypatch,
):
    sessions = import_db
    _, embedding, tags, milvus = cloud_services(monkeypatch)
    embedding.embed_media.side_effect = RuntimeError("private signed URL")
    await add_task(sessions, "failed")
    await import_router.process_import_task("failed", [FILE], "user-1", user_settings={})

    async with sessions() as session:
        task = await session.scalar(select(ImportTask).where(ImportTask.task_id == "failed"))
        media = await session.scalar(select(MediaFile))
        assert (task.status, task.processed_files, task.failed_files) == ("failed", 1, 1)
        assert (media.vector_status, media.tag_status) == ("failed", "done")
        assert "private" not in (task.error_message or "")
    tags.generate_tags.assert_awaited_once()
    milvus.upsert.assert_not_awaited()


async def test_custom_tag_failure_does_not_expose_prompt(
    import_db, monkeypatch, caplog,
):
    sessions = import_db
    secret_prompt = "confidential taxonomy instructions"
    _, _, tags, _ = cloud_services(monkeypatch)
    tags.generate_tags.side_effect = RuntimeError(secret_prompt)
    await add_task(
        sessions, "tag-failed",
        tag_mode="custom", custom_tag_prompt=secret_prompt,
    )

    await import_router.process_import_task(
        "tag-failed", [FILE], "user-1",
        generate_vectors=False, user_settings={},
    )

    tags.generate_tags.assert_awaited_once()
    assert tags.generate_tags.await_args.kwargs["tag_mode"] == "custom"
    assert tags.generate_tags.await_args.kwargs["custom_prompt"] == secret_prompt
    async with sessions() as session:
        task = await session.scalar(select(ImportTask))
        media = await session.scalar(select(MediaFile))
        assert (task.status, task.failed_files, media.tag_status) == ("failed", 1, "failed")
        assert secret_prompt not in (task.error_message or "")
    assert secret_prompt not in caplog.text


async def test_cancelled_worker_cannot_overwrite_terminal_status(
    import_db, monkeypatch,
):
    sessions = import_db
    _, embedding, _, _ = cloud_services(monkeypatch)
    entered = asyncio.Event()

    async def wait_forever(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    embedding.embed_media.side_effect = wait_forever
    await add_task(sessions, "cancel")
    worker = asyncio.create_task(import_router.process_import_task(
        "cancel", [FILE], "user-1", generate_tags=False, user_settings={},
    ))
    import_router._tasks["cancel"] = worker
    await entered.wait()
    async with sessions() as session:
        response = await import_router.cancel_task(
            "cancel", {"id": "user-1", "role": "user"}, session,
        )
    await asyncio.gather(worker, return_exceptions=True)

    async with sessions() as session:
        task = await session.scalar(select(ImportTask).where(ImportTask.task_id == "cancel"))
        media = await session.scalar(select(MediaFile))
        assert task.status == "cancelled"
        assert task.completed_at is not None
        assert media.vector_status == "failed"
    assert response.message == "任务已取消"


async def test_startup_recovery_accounts_for_failed_and_unattempted_files(
    import_db,
):
    sessions = import_db
    await add_task(sessions, "running", total=5, status="running", processed=2, failed=1)
    async with sessions() as session:
        session.add(MediaFile(
            user_id="user-1", tos_url=FILE["tos_url"],
            vector_status="processing", tag_status="processing",
        ))
        await session.commit()

    await import_router.recover_interrupted_imports()

    async with sessions() as session:
        task = await session.scalar(select(ImportTask))
        media = await session.scalar(select(MediaFile))
        assert (task.status, task.processed_files, task.failed_files) == ("failed", 5, 4)
        assert task.completed_at is not None
        assert (media.vector_status, media.tag_status) == ("failed", "failed")
        assert '"retryable": true' in task.error_message


async def test_import_missing_user_key_is_explicitly_empty(import_db, monkeypatch):
    _, embedding, tags, _ = cloud_services(monkeypatch)
    await add_task(import_db, "missing-key")
    await import_router.process_import_task(
        "missing-key", [FILE], "user-1", user_settings={"ark_api_key": None},
    )
    assert embedding.embed_media.await_args.kwargs["api_key"] == ""
    assert tags.generate_tags.await_args.kwargs["api_key"] == ""
