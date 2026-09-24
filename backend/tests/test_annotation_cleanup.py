"""Offline cleanup tests use temporary private frames, never original media."""

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.errors import ServiceError
from app.models.migrations import migrate
from app.models.models import (
    AnnotationFrame, AnnotationResultSet, AnnotationResultSetMember,
    AnnotationRun, MediaFile, MediaTag,
)
from app.services.annotation_cleanup_service import AnnotationCleanupService, FrameResource


def key(owner="owner-a", media="media-a", version="run-a", frame="a"):
    return f"{owner}/{media}/{version}/{frame * 32}.png"


async def setup_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    await migrate(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all([
            MediaFile(id=f"media-{suffix}", user_id=f"owner-{suffix}", tos_url=f"tos://bucket/{suffix}.mp4")
            for suffix in ("a", "b")
        ])
        await session.flush()
        session.add_all([
            AnnotationRun(
                id=f"run-{suffix}", user_id=f"owner-{suffix}", media_id=f"media-{suffix}",
                revision=1, status="completed", snapshot={"rule_hash": "a" * 64},
                idempotency_hash="a" * 64,
            )
            for suffix in ("a", "b")
        ])
        await session.flush()
        session.add_all([
            AnnotationFrame(
                id=f"frame-{suffix}", user_id=f"owner-{suffix}", run_id=f"run-{suffix}",
                frame_index=0, width=10, height=10, objects=[],
                storage_key=key(f"owner-{suffix}", f"media-{suffix}", f"run-{suffix}"),
            )
            for suffix in ("a", "b")
        ])
        session.add(MediaTag(id="tag-a", user_id="owner-a", media_id="media-a", tag_name="keep"))
        session.add(AnnotationResultSet(
            id="snapshot-b", user_id="owner-b", source={"tags": [], "logic": "AND"}, total=2,
            created_at=datetime(2026, 1, 1), expires_at=datetime(2026, 1, 2),
        ))
        await session.flush()
        session.add_all([
            AnnotationResultSetMember(snapshot_id="snapshot-b", user_id="owner-b", media_id=f"media-{suffix}")
            for suffix in ("a", "b")
        ])
        (await session.get(MediaFile, "media-a")).published_annotation_run_id = "run-a"
        await session.commit()
    return engine, sessions


def create_frames(root):
    paths = []
    for suffix in ("a", "b"):
        path = root / key(f"owner-{suffix}", f"media-{suffix}", f"run-{suffix}")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"offline-derived-frame")
        paths.append(path)
    return paths


def test_owner_cleanup_keeps_original_media_tags_and_other_users(tmp_path):
    async def scenario():
        engine, sessions = await setup_database()
        service = AnnotationCleanupService(tmp_path)
        owned_path, other_path = create_frames(tmp_path)
        try:
            async with sessions() as session:
                with pytest.raises(ServiceError) as caught:
                    await service.prepare_media_cleanup(session, user_id="owner-b", media_id="media-a")
                assert caught.value.status_code == 404
                await session.rollback()
                resources = await service.prepare_media_cleanup(session, user_id="owner-a", media_id="media-a")
                with pytest.raises(RuntimeError, match="Commit"):
                    await service.reclaim_frames(session, resources)
                assert owned_path.exists() and other_path.exists()
                await session.commit()
                assert await service.reclaim_frames(session, resources) == 1
                await session.commit()
                assert await service.reclaim_frames(session, resources) == 0
                assert not owned_path.exists() and other_path.exists()
                assert await session.get(MediaFile, "media-a") is not None
                assert await session.get(MediaTag, "tag-a") is not None
                assert await session.get(AnnotationRun, "run-a") is None
                assert await session.get(AnnotationRun, "run-b") is not None
                assert await session.get(AnnotationFrame, "frame-b") is not None
                assert (await session.get(MediaFile, "media-a")).published_annotation_run_id is None
                members = (await session.scalars(select(AnnotationResultSetMember))).all()
                assert [member.media_id for member in members] == ["media-b"]
                assert (await session.get(AnnotationResultSet, "snapshot-b")).total == 2
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_cleanup_rollback_keeps_rows_published_pointer_and_files(tmp_path):
    async def scenario():
        engine, sessions = await setup_database()
        service = AnnotationCleanupService(tmp_path)
        owned_path, _ = create_frames(tmp_path)
        try:
            async with sessions() as session:
                resources = await service.prepare_media_cleanup(session, user_id="owner-a", media_id="media-a")
                await session.rollback()
                assert await service.reclaim_frames(session, resources) == 0
                assert owned_path.exists()
                assert (await session.get(MediaFile, "media-a")).published_annotation_run_id == "run-a"
                assert await session.get(AnnotationFrame, "frame-a") is not None
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_reclaim_unpublished_version_preserves_reused_frame(tmp_path):
    async def scenario():
        engine, sessions = await setup_database()
        service = AnnotationCleanupService(tmp_path)
        owned_path, _ = create_frames(tmp_path)
        try:
            async with sessions() as session:
                session.add(AnnotationRun(
                    id="old-run", user_id="owner-a", media_id="media-a",
                    revision=2, status="failed", snapshot={}, idempotency_hash="a" * 64,
                ))
                await session.flush()
                session.add(AnnotationFrame(
                    id="old-frame", user_id="owner-a", run_id="old-run",
                    frame_index=0, width=10, height=10, storage_key=key(), objects=[],
                ))
                await session.commit()
                resources = await service.prepare_run_cleanup(
                    session, user_id="owner-a", media_id="media-a", run_id="old-run",
                )
                await session.commit()
                assert await service.reclaim_frames(session, resources) == 0
                assert owned_path.exists()
                assert await session.get(AnnotationRun, "old-run") is None
                assert (await session.get(MediaFile, "media-a")).published_annotation_run_id == "run-a"
        finally:
            await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["published", "active", "pending", "foreign"])
def test_individual_run_cleanup_protects_published_active_and_foreign(tmp_path, case):
    async def scenario():
        engine, sessions = await setup_database()
        service = AnnotationCleanupService(tmp_path)
        try:
            async with sessions() as session:
                if case in {"active", "pending"}:
                    run = await session.get(AnnotationRun, "run-a")
                    (await session.get(MediaFile, "media-a")).published_annotation_run_id = None
                    if case == "active":
                        run.active_key = "a" * 64
                    else:
                        run.status = "pending"
                    await session.commit()
                with pytest.raises(ServiceError) as caught:
                    await service.prepare_run_cleanup(
                        session, user_id="owner-a", media_id="media-a",
                        run_id="run-b" if case == "foreign" else "run-a",
                    )
                assert caught.value.status_code == (404 if case == "foreign" else 409)
        finally:
            await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.parametrize("storage_key", [
    "../owner-b/media-b/run-b/" + "a" * 32 + ".png",
    key(owner="owner-b", media="media-b", version="run-b"),
    "/absolute/" + key(),
    "owner-a/media-a/../" + "a" * 32 + ".png",
    "owner-a/media-a/run-a/anything.jpg",
])
def test_reclaim_rejects_traversal_and_wrong_owner(tmp_path, storage_key):
    async def scenario():
        engine, sessions = await setup_database()
        service = AnnotationCleanupService(tmp_path)
        try:
            async with sessions() as session:
                with pytest.raises(ServiceError) as caught:
                    await service.reclaim_frames(session, [FrameResource("owner-a", "media-a", storage_key)])
                assert caught.value.status_code == 422
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_reclaim_rejects_symlink_without_touching_target(tmp_path):
    async def scenario():
        engine, sessions = await setup_database()
        storage = tmp_path / "private"
        storage.mkdir()
        outside = tmp_path / "keep"
        outside.mkdir()
        target = outside / ("a" * 32 + ".png")
        target.write_bytes(b"not-an-annotation")
        parent = storage / "owner-a" / "media-a"
        parent.mkdir(parents=True)
        (parent / "run-a").symlink_to(outside, target_is_directory=True)
        try:
            async with sessions() as session:
                with pytest.raises(ServiceError):
                    await AnnotationCleanupService(storage).reclaim_frames(
                        session, [FrameResource("owner-a", "media-a", key())],
                    )
                assert target.read_bytes() == b"not-an-annotation"
        finally:
            await engine.dispose()
    asyncio.run(scenario())
