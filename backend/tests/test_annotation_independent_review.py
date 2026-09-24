"""Independent regression probes for the multimodal annotation acceptance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import import_router
from app.errors import MissingConfigurationError, ServiceError
from app.models.annotation_schemas import ANNOTATION_MODEL
from app.models.database import Base
from app.models.models import (
    AnnotationFrame, AnnotationRun, ImportTask, MediaFile, MediaTag,
    UserSystemSettings,
)
from app.services.annotation_frame_service import AnnotationFrameService
from app.services.annotation_job_service import AnnotationJobService


@pytest.mark.parametrize("size", [(7681, 1), (1, 7681), (4321, 4321)])
def test_image_frame_rejects_dimensions_beyond_published_8k_limits(tmp_path, size):
    source = tmp_path / f"too-large-{size[0]}x{size[1]}.png"
    Image.new("RGB", size).save(source)

    with pytest.raises(ServiceError):
        AnnotationFrameService()._upright_image(source)


async def test_annotation_job_uses_effective_default_model_and_only_owner_credentials():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(UserSystemSettings(
                user_id="owner",
                ark_api_key="offline-owner-key",
                tos_access_key_id="owner-ak",
                tos_access_key_secret="owner-sk",
                tag_model=None,
            ))
            await session.commit()

            config = await AnnotationJobService().owner_config(session, "owner")

        assert config["tag_model"] == ANNOTATION_MODEL
        assert config["ark_api_key"] == "offline-owner-key"
        assert config["tos_access_key_id"] == "owner-ak"
        assert config["tos_access_key_secret"] == "owner-sk"
        assert config["tos_bucket_name"] is None
    finally:
        await engine.dispose()


async def test_annotation_job_never_falls_back_to_deployment_credentials(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    for name in (
        "ARK_API_KEY", "TOS_ACCESS_KEY_ID", "TOS_ACCESS_KEY_SECRET",
        "TOS_BUCKET_NAME", "TOS_ENDPOINT", "TOS_REGION",
    ):
        monkeypatch.setattr(import_router.settings, name, f"deployment-{name.lower()}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(UserSystemSettings(user_id="owner", tag_model=None))
            await session.commit()

            with pytest.raises(MissingConfigurationError) as caught:
                await AnnotationJobService().owner_config(session, "owner")

        assert caught.value.missing_fields == ("ARK_API_KEY",)
    finally:
        await engine.dispose()


async def test_media_delete_reclaims_only_owned_frames_after_commit(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(import_router.settings, "ANNOTATION_STORAGE_DIR", str(tmp_path))
    owned_key = f"owner/media-a/run-a/{'a' * 32}.png"
    other_key = f"other/media-b/run-b/{'b' * 32}.png"
    owned_path = tmp_path / owned_key
    other_path = tmp_path / other_key
    for path in (owned_path, other_path):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"private frame")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add_all([
                MediaFile(id="media-a", user_id="owner", tos_url="tos://bucket/a.jpg"),
                MediaFile(id="media-b", user_id="other", tos_url="tos://bucket/b.jpg"),
            ])
            await session.flush()
            session.add_all([
                AnnotationRun(
                    id="run-a", user_id="owner", media_id="media-a", revision=1,
                    status="completed", snapshot={}, idempotency_hash="a" * 64,
                ),
                AnnotationRun(
                    id="run-b", user_id="other", media_id="media-b", revision=1,
                    status="completed", snapshot={}, idempotency_hash="b" * 64,
                ),
                MediaTag(user_id="owner", media_id="media-a", tag_name="owned"),
                MediaTag(user_id="other", media_id="media-b", tag_name="other"),
            ])
            await session.flush()
            session.add_all([
                AnnotationFrame(
                    id="frame-a", user_id="owner", run_id="run-a", frame_index=0,
                    width=10, height=10, storage_key=owned_key, objects=[],
                ),
                AnnotationFrame(
                    id="frame-b", user_id="other", run_id="run-b", frame_index=0,
                    width=10, height=10, storage_key=other_key, objects=[],
                ),
            ])
            await session.commit()

            await import_router.delete_media("media-a", {"id": "owner", "role": "user"}, session)

            assert await session.get(MediaFile, "media-a") is None
            assert await session.get(MediaFile, "media-b") is not None
            assert not owned_path.exists()
            assert other_path.exists()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("actor", [
    {"id": "other", "role": "user"},
    {"id": "admin", "role": "admin"},
])
async def test_media_delete_requires_owner_even_for_admin(tmp_path, monkeypatch, actor):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(import_router.settings, "ANNOTATION_STORAGE_DIR", str(tmp_path))
    owned_key = f"owner/media-a/run-a/{'a' * 32}.png"
    owned_path = tmp_path / owned_key
    owned_path.parent.mkdir(parents=True)
    owned_path.write_bytes(b"private frame")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(MediaFile(
                id="media-a", user_id="owner", tos_url="tos://bucket/a.jpg",
            ))
            await session.flush()
            session.add(AnnotationRun(
                id="run-a", user_id="owner", media_id="media-a", revision=1,
                status="completed", snapshot={}, idempotency_hash="a" * 64,
            ))
            await session.flush()
            session.add(AnnotationFrame(
                id="frame-a", user_id="owner", run_id="run-a", frame_index=0,
                width=10, height=10, storage_key=owned_key, objects=[],
            ))
            await session.commit()

            with pytest.raises(ServiceError) as caught:
                await import_router.delete_media("media-a", actor, session)

            assert caught.value.status_code == 404
            assert await session.get(MediaFile, "media-a") is not None
            assert await session.get(AnnotationFrame, "frame-a") is not None
            assert owned_path.exists()
    finally:
        await engine.dispose()


async def test_media_delete_commit_failure_keeps_database_and_frame(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(import_router.settings, "ANNOTATION_STORAGE_DIR", str(tmp_path))
    owned_key = f"owner/media-a/run-a/{'a' * 32}.png"
    owned_path = tmp_path / owned_key
    owned_path.parent.mkdir(parents=True)
    owned_path.write_bytes(b"private frame")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(MediaFile(
                id="media-a", user_id="owner", tos_url="tos://bucket/a.jpg",
            ))
            await session.flush()
            session.add(AnnotationRun(
                id="run-a", user_id="owner", media_id="media-a", revision=1,
                status="completed", snapshot={}, idempotency_hash="a" * 64,
            ))
            await session.flush()
            session.add(AnnotationFrame(
                id="frame-a", user_id="owner", run_id="run-a", frame_index=0,
                width=10, height=10, storage_key=owned_key, objects=[],
            ))
            await session.commit()
            monkeypatch.setattr(
                session, "commit", AsyncMock(side_effect=RuntimeError("commit failed")),
            )

            with pytest.raises(RuntimeError, match="commit failed"):
                await import_router.delete_media(
                    "media-a", {"id": "owner", "role": "user"}, session,
                )

        async with sessions() as verification:
            assert await verification.get(MediaFile, "media-a") is not None
            assert await verification.get(AnnotationRun, "run-a") is not None
            assert await verification.get(AnnotationFrame, "frame-a") is not None
        assert owned_path.exists()
    finally:
        await engine.dispose()


async def test_media_delete_preserves_frame_with_shared_database_reference(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(import_router.settings, "ANNOTATION_STORAGE_DIR", str(tmp_path))
    shared_key = f"owner/media-a/run-a/{'a' * 32}.png"
    shared_path = tmp_path / shared_key
    shared_path.parent.mkdir(parents=True)
    shared_path.write_bytes(b"shared private frame")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add_all([
                MediaFile(id="media-a", user_id="owner", tos_url="tos://bucket/a.jpg"),
                MediaFile(id="media-b", user_id="other", tos_url="tos://bucket/b.jpg"),
            ])
            await session.flush()
            session.add_all([
                AnnotationRun(
                    id="run-a", user_id="owner", media_id="media-a", revision=1,
                    status="completed", snapshot={}, idempotency_hash="a" * 64,
                ),
                AnnotationRun(
                    id="run-b", user_id="other", media_id="media-b", revision=1,
                    status="completed", snapshot={}, idempotency_hash="b" * 64,
                ),
            ])
            await session.flush()
            session.add_all([
                AnnotationFrame(
                    id="frame-a", user_id="owner", run_id="run-a", frame_index=0,
                    width=10, height=10, storage_key=shared_key, objects=[],
                ),
                AnnotationFrame(
                    id="frame-b", user_id="other", run_id="run-b", frame_index=0,
                    width=10, height=10, storage_key=shared_key, objects=[],
                ),
            ])
            await session.commit()

            await import_router.delete_media(
                "media-a", {"id": "owner", "role": "user"}, session,
            )

            assert await session.get(MediaFile, "media-a") is None
            assert await session.get(AnnotationFrame, "frame-a") is None
            assert await session.get(AnnotationFrame, "frame-b") is not None
            assert shared_path.exists()
    finally:
        await engine.dispose()


async def test_admin_cannot_cancel_another_users_annotation_import(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cancel = AsyncMock()
    monkeypatch.setattr(
        import_router,
        "annotation_job_service",
        SimpleNamespace(cancel=cancel),
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(ImportTask(
                user_id="owner",
                task_id="foreign-task",
                tos_directory="tos://owner-bucket/",
                status="running",
                annotation_status="running",
            ))
            await session.commit()

            with pytest.raises(HTTPException) as caught:
                await import_router.cancel_task(
                    "foreign-task",
                    {"id": "admin", "role": "admin"},
                    session,
                )

        assert caught.value.status_code == 404
        cancel.assert_not_awaited()
    finally:
        await engine.dispose()
