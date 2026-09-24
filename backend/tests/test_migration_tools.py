"""Offline migration-tool tests using SQLite and injected cloud fakes."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.errors import ServiceError, VectorSpaceMismatchError
from app.models.database import Base
from app.models.models import MediaFile, MediaTag, User, UserSystemSettings
from app.vector_space import VectorSpace
from scripts.migrate_metadata import (
    MigrationInputError,
    StorageMapping,
    load_export,
    map_storage_uri,
    migrate,
)
from scripts.rebuild_vectors import VectorRebuilder, vector_is_current


@pytest.fixture
def engine():
    value = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(value)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def mapping():
    return StorageMapping.parse(
        "oss://legacy-bucket/archive=tos://target-bucket/imported"
    )


@pytest.fixture
def export_payload():
    return {
        "format_version": 1,
        "tables": {
            "users": [{
                "id": "user-1",
                "username": "alice",
                "email": "alice@example.invalid",
                "password_hash": "preserved-password-hash",
                "role": "admin",
                "is_active": 1,
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            }],
            "media_files": [{
                "id": "media-1",
                "user_id": "user-1",
                "oss_url": "oss://legacy-bucket/archive/folder/a%2Bb.jpg",
                "file_type": "image",
                "file_name": "a+b.jpg",
                "file_size": 12,
                "vector_status": "done",
                "tag_status": "done",
                "vector_id": "legacy-vector",
                "vector_model": "legacy-model",
                "vector_dimension": 1024,
                "created_at": "2025-01-02T00:00:00Z",
                "updated_at": "2025-01-02T00:00:00Z",
            }],
            "media_tags": [{
                "id": "tag-1",
                "user_id": "user-1",
                "media_id": "media-1",
                "category": "weather",
                "tag_name": "manual-value",
                "confidence": 1.0,
                "is_manual": 1,
                "created_at": "2025-01-02T00:00:00Z",
            }],
            "import_tasks": [{
                "id": "import-1",
                "user_id": "user-1",
                "task_id": "task-1",
                "oss_directory": "oss://legacy-bucket/archive/",
                "status": "completed",
                "total_files": 1,
                "processed_files": 1,
                "failed_files": 0,
                "error_message": None,
                "created_at": "2025-01-02T00:00:00Z",
                "completed_at": "2025-01-02T00:01:00Z",
            }],
            "search_history": [{
                "id": "search-1",
                "user_id": "user-1",
                "search_type": "text",
                "query_content": "road",
                "result_count": 1,
                "created_at": "2025-01-03T00:00:00Z",
            }],
            "login_logs": [{
                "id": "login-1",
                "user_id": "user-1",
                "ip_address": "192.0.2.1",
                "user_agent": "test",
                "status": "success",
                "created_at": "2025-01-01T00:00:00Z",
            }],
            "user_sessions": [{
                "id": "session-1",
                "user_id": "user-1",
                "refresh_token": "preserved-session-token",
                "expires_at": "2025-02-01T00:00:00Z",
                "is_revoked": 1,
                "created_at": "2025-01-01T00:00:00Z",
            }],
            "user_system_settings": [{
                "id": "settings-1",
                "user_id": "user-1",
                "oss_access_key_id": "legacy-access-id-secret",
                "oss_access_key_secret": "legacy-access-secret",
                "dashscope_api_key": "legacy-model-secret",
                "embedding_model": "legacy-model",
                "embedding_dimension": 1024,
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            }],
        },
    }


def test_mapping_uses_longest_prefix_and_encodes_once():
    mappings = [
        StorageMapping.parse("oss://legacy-bucket=tos://target-bucket/root"),
        StorageMapping.parse(
            "oss://legacy-bucket/archive=tos://target-bucket/specific"
        ),
    ]
    assert map_storage_uri(
        "oss://legacy-bucket/archive/%E4%B8%AD%E6%96%87+a%23.jpg", mappings
    ) == "tos://target-bucket/specific/%E4%B8%AD%E6%96%87%2Ba%23.jpg"


def test_dry_run_is_default_and_does_not_write(engine, export_payload, mapping):
    original = copy.deepcopy(export_payload)
    with Session(engine) as session:
        report = migrate(session, export_payload, [mapping])
        assert report["valid"] is True
        assert report["mode"] == "dry-run"
        assert report["planned"]["media_files"] == 1
        assert session.scalar(select(func.count()).select_from(User)) == 0
    assert export_payload == original


def test_apply_preserves_history_and_is_idempotent(engine, export_payload, mapping):
    with Session(engine) as session:
        first = migrate(session, export_payload, [mapping], apply=True)
    assert all(count == 1 for count in first["inserted"].values())

    with Session(engine) as session:
        media = session.get(MediaFile, "media-1")
        user = session.get(User, "user-1")
        tag = session.get(MediaTag, "tag-1")
        saved = session.get(UserSystemSettings, "settings-1")
        assert media.tos_url == "tos://target-bucket/imported/folder/a%2Bb.jpg"
        assert media.vector_status == "pending"
        assert media.vector_id is None
        assert user.password_hash == "preserved-password-hash"
        assert tag.is_manual == 1
        assert tag.tag_name == "manual-value"
        assert saved.user_id == "user-1"
        assert saved.tos_access_key_id is None
        assert saved.tos_access_key_secret is None
        assert saved.ark_api_key is None
        second = migrate(session, export_payload, [mapping], apply=True)
    assert all(count == 0 for count in second["inserted"].values())
    assert all(count == 1 for count in second["already_present"].values())
    serialized = json.dumps(first)
    assert "legacy-access" not in serialized
    assert "legacy-model-secret" not in serialized


def test_source_file_is_never_modified(tmp_path, export_payload):
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export_payload), encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).digest()
    assert load_export(path) == export_payload
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda payload: payload["tables"]["users"].append(
                {
                    **payload["tables"]["users"][0],
                    "id": "user-2",
                    "username": "ALICE",
                    "email": "ALICE@EXAMPLE.INVALID",
                }
            ),
            "duplicate_username",
        ),
        (
            lambda payload: payload["tables"]["media_tags"][0].update(
                media_id="missing-media"
            ),
            "missing_relation",
        ),
    ],
)
def test_source_conflicts_block_apply(
    engine, export_payload, mapping, mutation, error
):
    mutation(export_payload)
    with Session(engine) as session, pytest.raises(MigrationInputError) as caught:
        migrate(session, export_payload, [mapping], apply=True)
    assert any(error in item for item in caught.value.report["errors"])
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_missing_object_mapping_blocks_apply(engine, export_payload):
    wrong = StorageMapping.parse("oss://other-bucket=tos://target-bucket/imported")
    with Session(engine) as session, pytest.raises(MigrationInputError) as caught:
        migrate(session, export_payload, [wrong], apply=True)
    assert any("storage_missing_mapping" in item for item in caught.value.report["errors"])


def test_target_primary_and_unique_conflicts_block_all_writes(
    engine, export_payload, mapping
):
    with Session(engine) as session:
        session.add(User(id="other-id", username="alice", password_hash="other"))
        session.commit()
        with pytest.raises(MigrationInputError) as caught:
            migrate(session, export_payload, [mapping], apply=True)
    assert any("target_username_conflict" in item for item in caught.value.report["errors"])
    with Session(engine) as session:
        assert session.get(MediaFile, "media-1") is None


class FakeTOS:
    def __init__(self, calls):
        self.calls = calls

    async def get_file_url(self, tos_url):
        self.calls.append(("tos", tos_url))
        return "https://signed.invalid/media?X-Tos-Signature=redacted"


class FakeEmbedding:
    def __init__(self, calls):
        self.calls = calls

    async def embed_media(
        self, tos_url, signed_url, *, model, dimension, api_key,
    ):
        assert signed_url.startswith("https://signed.invalid/")
        assert api_key == "user-ark-key"
        self.calls.append(("ark", tos_url, model, dimension))
        return [1.0] + [0.0] * 1023


class FakeMilvus:
    def __init__(self, calls, space, *, fail=False, config=None):
        self.calls = calls
        self.space = space
        self.fail = fail
        self.config = config or space.to_dict()
        self.ids = set()

    async def get_collection_config(self):
        self.calls.append(("milvus_config",))
        return self.config

    async def upsert(
        self, *, media_id, user_id, tos_url, file_type, embedding,
    ):
        assert len(embedding) == 1024
        assert embedding[0] == 1.0
        self.calls.append((
            "milvus_upsert", media_id, user_id, tos_url, file_type,
        ))
        if self.fail:
            raise ServiceError("milvus", "unavailable")
        self.ids.add(media_id)
        return media_id

    async def get_vector_count(self):
        self.calls.append(("milvus_count",))
        return len(self.ids)


def add_media(engine, **values):
    defaults = {
        "id": "media-1",
        "user_id": "user-1",
        "tos_url": "tos://target-bucket/media.jpg",
        "file_type": "image",
        "file_name": "media.jpg",
        "vector_status": "pending",
        "tag_status": "done",
    }
    with Session(engine) as session:
        session.add(User(
            id="user-1", username="owner", password_hash="hash",
        ))
        session.add(UserSystemSettings(
            id="settings-1", user_id="user-1",
            ark_api_key="user-ark-key",
        ))
        session.add(MediaFile(**{**defaults, **values}))
        session.add(
            MediaTag(
                id="manual-tag",
                user_id="user-1",
                media_id=defaults["id"],
                category="weather",
                tag_name="manual",
                is_manual=1,
            )
        )
        session.commit()


@pytest.mark.asyncio
async def test_old_done_version_rebuilds_in_required_order(engine):
    space = VectorSpace()
    add_media(
        engine,
        vector_status="done",
        vector_id="legacy-id",
        vector_model="legacy-model",
        vector_dimension=1024,
        vector_instruction_version="legacy-instruction",
        vector_collection="legacy-collection",
    )
    calls = []
    factory = sessionmaker(engine, expire_on_commit=False)
    milvus = FakeMilvus(calls, space)
    report = await VectorRebuilder(
        factory,
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=milvus,
        space=space,
    ).run(limit=1)
    assert [call[0] for call in calls] == [
        "milvus_config",
        "tos",
        "ark",
        "milvus_upsert",
        "milvus_count",
    ]
    assert report["succeeded"] == 1
    assert report["remaining"] == 0
    assert report["count_matches_mysql"] is True
    with Session(engine) as session:
        media = session.get(MediaFile, "media-1")
        assert vector_is_current(media, space)
        assert session.get(MediaTag, "manual-tag").tag_name == "manual"


@pytest.mark.asyncio
async def test_current_version_is_skipped_and_limit_is_resumable(engine):
    space = VectorSpace()
    add_media(
        engine,
        vector_status="done",
        vector_id="media-1",
        vector_model=space.model,
        vector_dimension=space.dimension,
        vector_instruction_version=space.corpus_instruction_version,
        vector_collection=space.collection,
    )
    calls = []
    report = await VectorRebuilder(
        sessionmaker(engine),
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=FakeMilvus(calls, space),
        space=space,
    ).run(limit=1)
    assert report["attempted"] == 0
    assert report["completed_for_space"] == 1
    assert all(call[0] not in {"tos", "ark", "milvus_upsert"} for call in calls)


@pytest.mark.asyncio
async def test_limit_and_after_id_form_stable_checkpoint(engine):
    space = VectorSpace()
    with Session(engine) as session:
        session.add(User(
            id="user-1", username="owner", password_hash="hash",
        ))
        session.add(UserSystemSettings(
            id="settings-1", user_id="user-1",
            ark_api_key="user-ark-key",
        ))
        session.add_all([
            MediaFile(
                id=media_id,
                user_id="user-1",
                tos_url=f"tos://target-bucket/{media_id}.jpg",
                file_type="image",
                file_name=f"{media_id}.jpg",
                vector_status="pending",
            )
            for media_id in ("media-a", "media-b")
        ])
        session.commit()
    calls = []
    factory = sessionmaker(engine, expire_on_commit=False)
    first = await VectorRebuilder(
        factory,
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=FakeMilvus(calls, space),
        space=space,
    ).run(limit=1)
    assert first["last_media_id"] == "media-a"
    assert first["remaining"] == 1

    second_milvus = FakeMilvus(calls, space)
    second_milvus.ids.add("media-a")
    second = await VectorRebuilder(
        factory,
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=second_milvus,
        space=space,
    ).run(limit=1, after_id=first["last_media_id"])
    assert second["last_media_id"] == "media-b"
    assert second["remaining"] == 0


@pytest.mark.asyncio
async def test_failure_is_recorded_then_failed_only_retry_succeeds(engine):
    space = VectorSpace()
    add_media(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    calls = []
    broken = FakeMilvus(calls, space, fail=True)
    first = await VectorRebuilder(
        factory,
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=broken,
        space=space,
    ).run()
    assert first["failed"] == 1
    assert first["failures"] == [{
        "media_id": "media-1",
        "error": "milvus:unavailable",
    }]
    with Session(engine) as session:
        media = session.get(MediaFile, "media-1")
        assert media.vector_status == "failed"
        assert media.vector_model is None
        assert media.vector_collection is None

    healthy = FakeMilvus(calls, space)
    second = await VectorRebuilder(
        factory,
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=healthy,
        space=space,
    ).run(failed_only=True)
    assert second["succeeded"] == 1
    with Session(engine) as session:
        assert vector_is_current(session.get(MediaFile, "media-1"), space)


@pytest.mark.asyncio
async def test_incompatible_collection_stops_before_tos_or_rds(engine):
    space = VectorSpace()
    add_media(engine)
    calls = []
    incompatible = {**space.to_dict(), "model": "legacy-model"}
    rebuilder = VectorRebuilder(
        sessionmaker(engine),
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=FakeMilvus(calls, space, config=incompatible),
        space=space,
    )
    with pytest.raises(VectorSpaceMismatchError):
        await rebuilder.run()
    assert calls == [("milvus_config",)]
    with Session(engine) as session:
        assert session.get(MediaFile, "media-1").vector_status == "pending"


@pytest.mark.asyncio
async def test_ownerless_legacy_media_must_be_assigned_before_rebuild(engine):
    space = VectorSpace()
    with Session(engine) as session:
        session.add(MediaFile(
            id="legacy-ownerless",
            tos_url="tos://target-bucket/legacy.jpg",
            file_type="image",
            vector_status="pending",
        ))
        session.commit()
    calls = []
    rebuilder = VectorRebuilder(
        sessionmaker(engine),
        tos=FakeTOS(calls),
        embedding=FakeEmbedding(calls),
        milvus=FakeMilvus(calls, space),
        space=space,
    )
    with pytest.raises(ServiceError) as captured:
        await rebuilder.run()
    assert captured.value.status_code == 409
    assert calls == []
