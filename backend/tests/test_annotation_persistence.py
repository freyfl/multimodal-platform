"""Offline annotation persistence and v3 -> v4 upgrade coverage."""

import asyncio
from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine, delete, event, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import database
from app.models.database import Base
from app.models.migrations import (
    MIGRATIONS, SchemaConflictError, _multimodal_annotations_v4,
    _v2_metadata, _v3_metadata, apply_migrations, schema_versions,
)
from app.models.models import (
    AnnotationFrame, AnnotationResultSet, AnnotationResultSetMember, AnnotationRun,
    ImportTask, MediaFile, MediaTag, User, UserSystemSettings,
)
from app.models.annotation_schemas import AnnotationOptions
from app.services.annotation_rules import ANNOTATION_MODEL, build_rule_snapshot


def foreign_keys(dbapi_connection, _):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", foreign_keys)
    with engine.begin() as connection:
        apply_migrations(connection)
    try:
        yield engine
    finally:
        engine.dispose()


def rule_snapshot():
    return build_rule_snapshot(
        AnnotationOptions(), model=ANNOTATION_MODEL,
        source_etag="etag-A", source_version="version-A",
    ).model_dump(mode="json")


def run_record(identity="run-a", owner="owner-a", media_id="media-a", **kwargs):
    fields = dict(
        id=identity, user_id=owner, media_id=media_id, revision=1,
        snapshot=rule_snapshot(), source_etag="etag-A", source_version="version-A",
        idempotency_hash="a" * 64,
    )
    fields.update(kwargs)
    return AnnotationRun(**fields)


def frame_record(identity="frame-a", owner="owner-a", run_id="run-a", **kwargs):
    fields = dict(
        id=identity, user_id=owner, run_id=run_id, frame_index=0,
        width=1920, height=1080, timestamp_ms=None, objects=[],
    )
    fields.update(kwargs)
    return AnnotationFrame(**fields)


def seed_media(session):
    session.add_all([
        MediaFile(id="media-a", user_id="owner-a", tos_url="tos://bucket/a.mp4"),
        MediaFile(id="media-b", user_id="owner-b", tos_url="tos://bucket/b.mp4"),
    ])
    session.flush()


def seed_v3(connection):
    _v3_metadata.create_all(connection)
    schema_versions.create(connection)
    connection.execute(schema_versions.insert(), [
        {"version": version, "name": name, "applied_at": datetime(2026, 1, 1)}
        for version, name, _ in MIGRATIONS[:3]
    ])
    rows = {
        "users": dict(id="owner-a", username="old", password_hash="unchanged-hash"),
        "user_system_settings": dict(
            id="settings-a", user_id="owner-a", tos_bucket_name="unchanged-bucket",
            ark_api_key="fake-offline-key", embedding_dimension=1024,
        ),
        "media_files": dict(
            id="media-a", user_id="owner-a", tos_url="tos://bucket/old.jpg",
            file_size=2**33, vector_id="unchanged-vector",
            vector_collection="media_vectors_v2", vector_status="done", tag_status="done",
        ),
        "media_tags": dict(
            id="tag-a", user_id="owner-a", media_id="media-a",
            source="custom", category="road", tag_name="old", is_manual=1,
        ),
        "import_tasks": dict(
            id="task-row-a", task_id="task-a", user_id="owner-a",
            status="completed", tag_mode="custom", custom_tag_prompt="unchanged",
            total_files=4, processed_files=4, failed_files=0,
        ),
    }
    for name, row in rows.items():
        connection.execute(_v3_metadata.tables[name].insert().values(**row))


def test_new_sqlite_initialization_is_repeatable_and_exports_models(engine):
    import app.models as exported

    with engine.begin() as connection:
        apply_migrations(connection)
        apply_migrations(connection)
        assert connection.execute(select(schema_versions.c.version)).scalars().all() == [1, 2, 3, 4]
        assert not connection.execute(text("PRAGMA foreign_key_check")).all()
    assert len(Base.metadata.tables) == 12
    assert len(inspect(engine).get_table_names()) == 13
    for cls in (AnnotationRun, AnnotationFrame, AnnotationResultSet, AnnotationResultSetMember):
        assert getattr(exported, cls.__name__) is cls
    assert "annotation_status" not in _v2_metadata.tables["media_files"].c
    assert "annotation_config" not in _v3_metadata.tables["import_tasks"].c


def test_async_init_db_with_injected_sqlite_engine(monkeypatch):
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        event.listen(engine.sync_engine, "connect", foreign_keys)
        monkeypatch.setattr(database, "get_engine", lambda: engine)
        try:
            await database.init_db()
            await database.init_db()
            async with engine.connect() as connection:
                assert (await connection.scalars(select(schema_versions.c.version))).all() == [1, 2, 3, 4]
        finally:
            await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.parametrize("resume", [False, True])
def test_v3_incremental_migration_preserves_all_historical_data(resume):
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", foreign_keys)
    try:
        with engine.begin() as connection:
            seed_v3(connection)
        if resume:
            # Simulate auto-committed MySQL DDL without its version marker.
            with engine.begin() as connection:
                _multimodal_annotations_v4(connection)
        with engine.begin() as connection:
            apply_migrations(connection)
            apply_migrations(connection)
            assert not connection.execute(text("PRAGMA foreign_key_check")).all()
        with Session(engine) as session:
            media = session.get(MediaFile, "media-a")
            assert media.annotation_status == "not_started"
            assert media.published_annotation_run_id is None
            assert (media.vector_id, media.vector_collection, media.file_size) == (
                "unchanged-vector", "media_vectors_v2", 2**33,
            )
            assert media.tag_status == media.vector_status == "done"
            tag = session.get(MediaTag, "tag-a")
            assert (tag.source, tag.is_manual, tag.tag_name) == ("custom", 1, "old")
            task = session.get(ImportTask, "task-row-a")
            assert task.annotation_status == "not_started"
            assert task.annotation_config is None
            assert task.annotation_planned_frames == task.annotation_total_files == 0
            assert (task.processed_files, task.custom_tag_prompt) == (4, "unchanged")
            assert session.get(User, "owner-a").password_hash == "unchanged-hash"
            settings = session.get(UserSystemSettings, "settings-a")
            assert settings.ark_api_key == "fake-offline-key"
            assert settings.tos_bucket_name == "unchanged-bucket"
    finally:
        engine.dispose()


def test_v4_partial_column_addition_resumes_without_rebuilding():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            seed_v3(connection)
            connection.execute(text(
                "ALTER TABLE media_files ADD COLUMN published_annotation_run_id "
                "VARCHAR(36) REFERENCES annotation_runs(id) ON DELETE SET NULL"
            ))
            connection.execute(text(
                "ALTER TABLE import_tasks ADD COLUMN annotation_config JSON"
            ))
        with engine.begin() as connection:
            apply_migrations(connection)
        with Session(engine) as session:
            assert session.get(MediaFile, "media-a").annotation_status == "not_started"
    finally:
        engine.dispose()


def test_v4_resumes_after_create_table_before_all_indexes():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            seed_v3(connection)
            _multimodal_annotations_v4(connection)
            connection.execute(text("DROP INDEX ix_annotation_frames_storage_key"))
        with engine.begin() as connection:
            apply_migrations(connection)
            apply_migrations(connection)
        assert "ix_annotation_frames_storage_key" in {
            index["name"] for index in inspect(engine).get_indexes("annotation_frames")
        }
    finally:
        engine.dispose()


def test_missing_annotation_table_is_not_silently_recreated(engine):
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE annotation_frames"))
    with engine.begin() as connection, pytest.raises(SchemaConflictError, match="missing"):
        apply_migrations(connection)
    assert "annotation_frames" not in inspect(engine).get_table_names()


def test_snapshot_progress_json_round_trip(engine):
    with Session(engine) as session:
        seed_media(session)
        session.add(ImportTask(
            id="row-a", task_id="task-a", user_id="owner-a",
            annotation_config=rule_snapshot(), annotation_status="running",
            annotation_total_files=2, annotation_processed_files=1,
            annotation_planned_frames=60, annotation_processed_frames=10,
            annotation_completed_frames=9, annotation_failed_frames=1,
            annotation_current_media_id="media-a", annotation_current_frame_index=9,
        ))
        session.flush()
        session.add(run_record(task_id="task-a"))
        session.commit()
        session.expire_all()
        run = session.get(AnnotationRun, "run-a")
        assert run.snapshot == rule_snapshot()
        assert (run.source_etag, run.source_version) == ("etag-A", "version-A")
        task = session.get(ImportTask, "row-a")
        assert task.annotation_completed_frames == 9
        assert task.annotation_config["rule_hash"] == run.snapshot["rule_hash"]
        session.execute(delete(ImportTask).where(ImportTask.task_id == "task-a"))
        session.commit()
        assert session.get(AnnotationRun, "run-a").task_id is None


def test_duplicate_frame_index_rejected_but_other_runs_allowed(engine):
    with Session(engine) as session:
        seed_media(session)
        session.add_all([run_record(), run_record("run-b", revision=2)])
        session.flush()
        session.add_all([frame_record(), frame_record("frame-b", run_id="run-b")])
        session.commit()
        session.add(frame_record("duplicate"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert len(session.scalars(select(AnnotationFrame)).all()) == 2


def test_revision_unique_and_hash_reusable_after_active_key_release(engine):
    with Session(engine) as session:
        seed_media(session)
        session.add(run_record(active_key="a" * 64))
        session.commit()
        session.add(run_record("duplicate-revision"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(run_record("duplicate-active", revision=2, active_key="a" * 64))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        old = session.get(AnnotationRun, "run-a")
        old.active_key = None
        old.status = "completed"
        session.commit()
        session.add(run_record("forced", revision=2, active_key="a" * 64))
        session.commit()
        assert session.get(AnnotationRun, "forced").idempotency_hash == old.idempotency_hash


@pytest.mark.parametrize("kind", ["run", "frame", "member"])
def test_composite_foreign_keys_reject_cross_owner_records(engine, kind):
    with Session(engine) as session:
        seed_media(session)
        session.add(run_record())
        session.add(AnnotationResultSet(
            id="snapshot-a", user_id="owner-a", source={"tags": [], "logic": "AND"},
            created_at=datetime(2026, 1, 1), expires_at=datetime(2026, 1, 2),
        ))
        session.commit()
        row = {
            "run": lambda: run_record("bad", owner="owner-b"),
            "frame": lambda: frame_record(owner="owner-b"),
            "member": lambda: AnnotationResultSetMember(
                snapshot_id="snapshot-a", media_id="media-a", user_id="owner-b",
            ),
        }[kind]()
        session.add(row)
        with pytest.raises(IntegrityError):
            session.commit()


def test_result_set_membership_unique_and_snapshot_cascade(engine):
    with Session(engine) as session:
        seed_media(session)
        session.add(AnnotationResultSet(
            id="snapshot-a", user_id="owner-a", source={"tags": [], "logic": "AND"}, total=2,
            created_at=datetime(2026, 1, 1), expires_at=datetime(2026, 1, 2),
        ))
        session.flush()
        # Admin-created snapshots may contain another owner's visible media.
        session.add_all([
            AnnotationResultSetMember(snapshot_id="snapshot-a", user_id="owner-a", media_id=media)
            for media in ("media-a", "media-b")
        ])
        session.commit()
        session.add(AnnotationResultSetMember(
            snapshot_id="snapshot-a", media_id="media-a", user_id="owner-a",
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.execute(delete(AnnotationResultSet))
        session.commit()
        assert not session.scalars(select(AnnotationResultSetMember)).all()
        assert len(session.scalars(select(MediaFile)).all()) == 2


def test_published_pointer_transaction_rollback_and_media_cascade(engine):
    with Session(engine) as session:
        seed_media(session)
        session.add_all([
            run_record(status="completed"),
            run_record("replacement", revision=2, status="running"),
            run_record("run-b", owner="owner-b", media_id="media-b"),
        ])
        session.flush()
        session.add_all([frame_record(), frame_record("frame-b", owner="owner-b", run_id="run-b")])
        session.get(MediaFile, "media-a").published_annotation_run_id = "run-a"
        session.commit()
        session.get(AnnotationRun, "replacement").status = "completed"
        session.get(MediaFile, "media-a").published_annotation_run_id = "replacement"
        session.flush()
        session.rollback()
        assert session.get(MediaFile, "media-a").published_annotation_run_id == "run-a"
        assert session.get(AnnotationRun, "replacement").status == "running"
        session.execute(delete(MediaFile).where(MediaFile.id == "media-a", MediaFile.user_id == "owner-a"))
        session.commit()
        assert session.get(AnnotationRun, "run-a") is None
        assert session.get(AnnotationFrame, "frame-a") is None
        assert session.get(AnnotationRun, "run-b") is not None
        assert session.get(AnnotationFrame, "frame-b") is not None


def test_run_delete_sets_published_pointer_null_and_cascades_frames(engine):
    with Session(engine) as session:
        seed_media(session)
        session.add(run_record(status="completed"))
        session.flush()
        session.add(frame_record())
        session.get(MediaFile, "media-a").published_annotation_run_id = "run-a"
        session.commit()
        session.execute(delete(AnnotationRun).where(AnnotationRun.id == "run-a"))
        session.commit()
        assert session.get(MediaFile, "media-a").published_annotation_run_id is None
        assert session.get(AnnotationFrame, "frame-a") is None


@pytest.mark.parametrize("fields", [
    {"width": 0}, {"height": -1}, {"frame_index": -1},
    {"timestamp_ms": -0.1}, {"status": "invalid"}, {"model_elapsed_ms": -1},
])
def test_frame_scalar_constraints(engine, fields):
    with Session(engine) as session:
        seed_media(session)
        session.add(run_record())
        session.commit()
        session.add(frame_record(**fields))
        with pytest.raises(IntegrityError):
            session.commit()


def test_mysql_v4_ddl_is_additive_and_compiles_without_server():
    connection = Mock()
    connection.dialect = mysql.dialect()
    inspector = Mock()
    inspector.get_columns.side_effect = lambda name: [
        {"name": name} for name in _v3_metadata.tables[name].columns.keys()
    ]
    inspector.get_indexes.return_value = []
    inspector.get_table_names.return_value = []
    inspector.get_foreign_keys.return_value = []
    with patch("app.models.migrations.inspect", return_value=inspector), patch.object(
        Base.metadata, "create_all",
    ) as create:
        _multimodal_annotations_v4(connection)
    statements = "\n".join(
        str(call.args[0].compile(dialect=mysql.dialect()))
        for call in connection.execute.call_args_list
    )
    assert "ADD COLUMN annotation_config JSON" in statements
    assert "annotation_status VARCHAR(20) NOT NULL DEFAULT 'not_started'" in statements
    assert "ON DELETE SET NULL" in statements
    assert "DROP " not in statements and "UPDATE " not in statements
    assert len(create.call_args.kwargs["tables"]) == 4
    for name in ("annotation_runs", "annotation_frames", "annotation_result_sets", "annotation_result_set_members"):
        table = Base.metadata.tables[name]
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "InnoDB" in ddl
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=mysql.dialect()))
