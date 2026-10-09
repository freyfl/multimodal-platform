"""Offline three-mode regression: SQLite, Ark HTTP and TOS/Milvus mocks."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps, search_router, tags_router
from app.errors import ServiceError
from app.models import database
from app.models.models import MediaFile, MediaTag, SearchHistory, UserSystemSettings
from app.services import search_service as search_module
from app.services.ark_client import ArkClient
from app.services.embedding_service import EmbeddingService
from app.services.tag_service import DEFAULT_TAG_PROMPT
from app.services.tos_service import TOSService
from app.vector_space import IMAGE_QUERY_INSTRUCTION, TEXT_QUERY_INSTRUCTION


SPECIAL_KEY = "\u4e2d\u6587/road +%#?.png"
VECTOR = [1.0] + [0.0] * 1023
IMAGE = b"offline-image-payload"


@pytest.fixture
async def api(monkeypatch, empty_settings):
    config = empty_settings.model_copy(update={
        "TOS_BUCKET_NAME": "global-bucket",
        "ARK_API_KEY": "global-ark-key",
        "ARK_MAX_RETRIES": 0,
    })
    monkeypatch.setattr(deps, "settings", config)
    monkeypatch.setattr(search_module, "settings", config)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", sessions)
    await database.init_db()
    space = config.vector_space
    urls = [
        f"tos://user-bucket/{SPECIAL_KEY}",
        "tos://user-bucket/second.mp4",
        "tos://user-bucket/third.png",
    ]
    async with sessions() as session:
        session.add(UserSystemSettings(
            user_id="user-1", tos_access_key_id="user-ak",
            tos_access_key_secret="user-secret", tos_security_token="user-token",
            tos_bucket_name="user-bucket", tos_endpoint="https://tos.invalid",
            tos_region="cn-beijing", ark_api_key="user-ark-key",
            embedding_model=space.model, embedding_dimension=space.dimension,
        ))
        session.add(UserSystemSettings(
            user_id="user-2", tos_access_key_id="other-ak",
            tos_access_key_secret="other-secret", tos_bucket_name="other-bucket",
            tos_endpoint="https://tos.invalid", tos_region="cn-beijing",
            embedding_model=space.model, embedding_dimension=space.dimension,
        ))
        for index, url in enumerate(urls):
            session.add(MediaFile(
                id=f"media-{index}", user_id="user-1", tos_url=url,
                file_type="video" if index == 1 else "image",
                file_name=f"file-{index}", vector_status="done",
                vector_model=space.model, vector_dimension=space.dimension,
                vector_instruction_version=space.corpus_instruction_version,
                vector_collection=space.collection,
            ))
            session.add(MediaTag(
                user_id="user-1", media_id=f"media-{index}", category="road",
                tag_name="highway", source="default", is_manual=index == 0,
            ))
        session.add(MediaTag(
            user_id="user-1", media_id="media-0",
            source="default", category="weather", tag_name="rain",
        ))
        session.add(MediaTag(
            user_id="user-1", media_id="media-0",
            source="custom", category="road", tag_name="highway",
        ))
        session.add(MediaTag(
            user_id="user-1", media_id="orphan",
            source="custom", category="orphan", tag_name="hidden",
        ))
        session.add(MediaTag(
            user_id="user-2", media_id="media-0",
            source="custom", category="road", tag_name="foreign-owner-tag",
        ))
        session.add(MediaFile(
            id="media-custom", user_id="user-1",
            tos_url="tos://user-bucket/custom.png",
            file_type="image", file_name="custom.png",
        ))
        session.add(MediaTag(
            user_id="user-1", media_id="media-custom",
            source="custom", category="road", tag_name="highway",
        ))
        session.add(MediaTag(
            user_id="user-1", media_id="media-custom",
            source="custom", category="hazard", tag_name="cone",
        ))
        session.add(MediaFile(
            id="media-other", user_id="user-2",
            tos_url="tos://other-bucket/private.png",
            file_type="image", file_name="private.png",
        ))
        session.add(MediaTag(
            user_id="user-2", media_id="media-other",
            source="default", category="road", tag_name="highway",
        ))
        session.add(MediaTag(
            user_id="user-2", media_id="media-other",
            source="custom", category="hazard", tag_name="barrier",
        ))
        await session.commit()

    requests = []

    def embed_response(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"embedding": VECTOR}})

    ark_handler = Mock(side_effect=embed_response)
    ark_http = httpx.AsyncClient(transport=httpx.MockTransport(ark_handler))
    embedding = EmbeddingService(client=ArkClient(config=config, http_client=ark_http))
    monkeypatch.setattr(search_module, "embedding_service", embedding)
    milvus = SimpleNamespace(
        get_collection_config=AsyncMock(return_value=space.to_dict()),
        search=AsyncMock(return_value=[
            {"media_id": f"media-{index}", "tos_url": url,
             "user_id": "user-1",
             "file_type": "video" if index == 1 else "image", "score": score}
            for index, (url, score) in enumerate(zip(urls, [-0.3, 1.4, 0.6]))
        ]),
    )
    monkeypatch.setattr(search_module, "milvus_service", milvus)
    storages, effective_configs, sdk_clients = [], [], []

    def storage_factory(effective):
        effective_configs.append(dict(effective))
        sdk = Mock()
        sdk.pre_signed_url.side_effect = lambda **kwargs: SimpleNamespace(
            signed_url=(
                f"https://{kwargs['bucket']}.tos.invalid/"
                f"{quote(kwargs['key'], safe='/')}?X-Tos-Signature=keep%2B%25&x=1"
            ),
        )
        storage = TOSService(
            **{name: effective.get(f"tos_{name}") or "" for name in (
                "access_key_id", "access_key_secret", "security_token",
                "bucket_name", "endpoint", "region", "custom_domain",
            )},
            client=sdk,
        )
        storages.append(storage)
        sdk_clients.append(sdk)
        return storage

    monkeypatch.setattr(TOSService, "from_settings", storage_factory)
    app = FastAPI()
    app.include_router(search_router.router, prefix="/api")
    app.include_router(tags_router.router, prefix="/api")
    app.dependency_overrides[deps.get_current_user] = lambda: {
        "id": "user-1", "role": "user", "is_demo": 0,
    }

    @app.exception_handler(ServiceError)
    async def service_error(request, error):
        return search_router._error_response(error)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        yield SimpleNamespace(
            app=app, client=client, sessions=sessions, milvus=milvus,
            requests=requests, ark_handler=ark_handler, config=config,
            effective_configs=effective_configs, sdk_clients=sdk_clients, urls=urls,
        )
    for storage in storages:
        await storage.aclose()
    await embedding.aclose()
    await ark_http.aclose()
    await database.close_db()
    for sdk in sdk_clients:
        sdk.close.assert_called_once()


async def search(api, mode, **kwargs):
    if mode == "text":
        return await api.client.post("/api/search/text", json={"query": "original query", **kwargs})
    if mode == "tags":
        return await api.client.post("/api/search/tags", json={
            "tags": [{
                "source": "default", "category": "road", "name": "highway",
            }], **kwargs,
        })
    return await api.client.post(
        "/api/search/image", data=kwargs,
        files={"image": ("photo.png", IMAGE, "image/png")},
    )


@pytest.mark.parametrize("mode", ["text", "image", "tags"])
async def test_three_modes_user_previews_tags_history_and_canonical_uri(api, mode):
    response = await search(api, mode)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 200 and body["message"] == "success"
    assert body["data"]["total"] == 3
    items = body["data"]["items"]
    special = next(item for item in items if item["media_id"] == "media-0")
    assert special["tos_url"] == api.urls[0]
    assert special["preview_url"] == (
        f"https://user-bucket.tos.invalid/{quote(SPECIAL_KEY, safe='/')}"
        "?X-Tos-Signature=keep%2B%25&x=1"
    )
    assert any(tag["is_manual"] for tag in special["tags"])
    assert {tag["source"] for tag in special["tags"]} == {"default", "custom"}
    assert "oss_url" not in special
    assert "/api/tos/" not in special["preview_url"]
    effective = api.effective_configs[0]
    assert effective["tos_access_key_secret"] == "user-secret"
    assert effective["tos_security_token"] == "user-token"
    assert effective["tos_bucket_name"] == "user-bucket"
    assert effective["is_custom"]
    calls = [
        call for sdk in api.sdk_clients
        for call in sdk.pre_signed_url.call_args_list
    ]
    assert any(call.kwargs["key"] == SPECIAL_KEY for call in calls)
    if mode == "tags":
        assert body["data"]["page"] == 1 and body["data"]["size"] == 20
        assert not api.requests
        api.milvus.get_collection_config.assert_not_awaited()
    else:
        assert [item["similarity"] for item in items] == [1.0, 0.6, 0.0]
        request = api.requests[0]
        assert request.headers["authorization"] == "Bearer user-ark-key"
        payload = json.loads(request.content)
        assert payload["dimensions"] == 1024
        assert payload["instructions"] == (
            TEXT_QUERY_INSTRUCTION if mode == "text" else IMAGE_QUERY_INSTRUCTION
        )
        if mode == "text":
            assert payload["input"] == [{"type": "text", "text": "original query"}]
        else:
            assert payload["input"][0]["image_url"]["url"] == (
                "data:image/png;base64," + base64.b64encode(IMAGE).decode()
            )
    async with api.sessions() as session:
        history = (await session.execute(select(SearchHistory))).scalar_one()
        assert history.search_type == ("tag" if mode == "tags" else mode)
        assert "data:" not in history.query_content
        assert "Signature" not in history.query_content
        if mode == "tags":
            assert json.loads(history.query_content)[0]["source"] == "default"
        assert (await session.get(MediaFile, "media-0")).tos_url == api.urls[0]


async def test_tag_and_or_stable_pagination_excludes_orphans(api):
    tags = [
        {"source": "default", "category": "road", "name": "highway"},
        {"source": "default", "category": "weather", "name": "rain"},
    ]
    response = await search(api, "tags", tags=tags)
    assert response.json()["data"]["total"] == 1
    response = await search(api, "tags", tags=tags, logic="OR", page=2, size=1)
    assert response.json()["data"]["total"] == 3
    assert response.json()["data"]["items"][0]["media_id"] == "media-1"
    response = await search(api, "tags", page=5, size=1)
    assert response.json()["data"] == {"items": [], "total": 3, "page": 5, "size": 1}


async def test_tag_search_requires_matching_media_and_tag_owner(api):
    response = await search(api, "tags", tags=[{
        "source": "custom", "category": "road", "name": "foreign-owner-tag",
    }])
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0


async def test_tag_search_distinguishes_sources_and_supports_mixed_logic(api):
    default_tag = {"source": "default", "category": "road", "name": "highway"}
    custom_tag = {"source": "custom", "category": "road", "name": "highway"}
    response = await search(api, "tags", tags=[default_tag])
    assert response.json()["data"]["total"] == 3
    response = await search(api, "tags", tags=[custom_tag])
    assert response.json()["data"]["total"] == 2
    response = await search(api, "tags", tags=[default_tag, custom_tag])
    assert response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["media_id"] == "media-0"
    response = await search(
        api, "tags", tags=[default_tag, custom_tag], logic="OR",
    )
    assert response.json()["data"]["total"] == 4


async def test_tag_catalog_aggregates_visible_custom_tags(api):
    response = await api.client.get("/api/tags")
    assert response.status_code == 200
    catalog = response.json()["data"]
    assert catalog["default"]
    assert all(item["source"] == "default" for item in catalog["default"])
    assert catalog["default_prompt"] == DEFAULT_TAG_PROMPT
    assert catalog["custom"] == [
        {"source": "custom", "category": "hazard", "name": "cone"},
        {"source": "custom", "category": "road", "name": "highway"},
    ]


async def test_admin_has_global_tag_catalog_and_search(api):
    api.app.dependency_overrides[deps.get_current_user] = lambda: {
        "id": "user-1", "role": "admin", "is_demo": 0,
    }
    response = await api.client.get("/api/tags")
    assert response.status_code == 200
    assert response.json()["data"]["custom"] == [
        {"source": "custom", "category": "hazard", "name": "barrier"},
        {"source": "custom", "category": "hazard", "name": "cone"},
        {"source": "custom", "category": "road", "name": "highway"},
    ]
    response = await search(api, "tags")
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 4
    assert {item["media_id"] for item in response.json()["data"]["items"]} == {
        "media-0", "media-1", "media-2", "media-other",
    }
    media_zero = next(
        item for item in response.json()["data"]["items"]
        if item["media_id"] == "media-0"
    )
    assert all(tag["tag_name"] != "foreign-owner-tag" for tag in media_zero["tags"])


async def test_manual_tag_edit_validates_and_preserves_source(api):
    tags = [
        {"source": "default", "category": "road", "name": "高速公路"},
        {"source": "custom", "category": " road ", "name": " 高速公路 "},
        {"source": "custom", "category": "road", "name": "高速公路"},
    ]
    response = await api.client.put(
        "/api/tags/media/media-0", json={"tags": tags},
    )
    assert response.status_code == 200
    response = await api.client.get("/api/tags/media/media-0")
    assert response.status_code == 200
    assert {
        (tag["source"], tag["category"], tag["tag_name"])
        for tag in response.json()
    } == {
        ("default", "road", "高速公路"),
        ("custom", "road", "高速公路"),
    }
    async with api.sessions() as session:
        saved = (await session.scalars(select(MediaTag).where(
            MediaTag.media_id == "media-0",
            MediaTag.user_id == "user-1",
        ))).all()
        assert len(saved) == 2
        assert all(tag.is_manual for tag in saved)

    invalid_tags = [
        {"source": "default", "category": "road", "name": "not-in-defaults"},
        {"source": "custom", "category": " ", "name": "dynamic"},
        {"source": "custom", "category": "dynamic", "name": "x" * 101},
        {"category": "road", "name": "高速公路"},
    ]
    for tag in invalid_tags:
        response = await api.client.put(
            "/api/tags/media/media-0", json={"tags": [tag]},
        )
        assert response.status_code == 400


async def test_threshold_clamp_top_k_and_configured_text_threshold(api, monkeypatch):
    response = await search(api, "image", threshold=0.6, top_k=2)
    assert [item["similarity"] for item in response.json()["data"]["items"]] == [1.0, 0.6]
    assert api.milvus.search.call_args.kwargs["min_score"] == 0.6
    monkeypatch.setattr(search_module, "settings", api.config.model_copy(update={"TEXT_SEARCH_MIN_SCORE": 0.7}))
    response = await search(api, "text")
    assert response.json()["data"]["total"] == 1
    assert api.milvus.search.call_args.kwargs["min_score"] == 0.7


@pytest.mark.parametrize("field,value", [
    ("model", "other-model"), ("dimension", 768), ("dimension", 1024.0),
    ("corpus_instruction_version", "old"), ("query_instruction_version", "old"),
    ("collection", "old-collection"), ("model", None),
])
@pytest.mark.parametrize("mode", ["text", "image"])
async def test_full_collection_space_required_before_embedding(api, field, value, mode):
    api.milvus.get_collection_config.return_value = {
        **api.config.vector_space.to_dict(), field: value,
    }
    response = await search(api, mode)
    assert response.status_code == 409
    assert response.json()["data"]["category"] == "incompatible_vector_space"
    assert not api.requests
    api.milvus.search.assert_not_awaited()


@pytest.mark.parametrize("mode", ["text", "image"])
async def test_dimension_only_metadata_never_guesses_model(api, mode):
    api.milvus.get_collection_config.return_value = {"dimension": 1024}
    response = await search(api, mode)
    assert response.status_code == 409
    assert not api.requests


@pytest.mark.parametrize("field,value", [
    ("vector_model", "old-model"), ("vector_dimension", 768),
    ("vector_instruction_version", None), ("vector_collection", "old"),
])
async def test_stale_rds_vector_identity_is_not_returned(api, field, value):
    async with api.sessions() as session:
        media = await session.get(MediaFile, "media-0")
        setattr(media, field, value)
        await session.commit()
    response = await search(api, "text")
    assert response.status_code == 409


@pytest.mark.parametrize("mode", ["text", "image", "tags"])
async def test_user_bucket_mismatch_never_uses_global_proxy(api, mode):
    async with api.sessions() as session:
        saved = await session.scalar(select(UserSystemSettings).where(
            UserSystemSettings.user_id == "user-1",
        ))
        saved.tos_bucket_name = "different-bucket"
        await session.commit()
    response = await search(api, mode)
    assert response.status_code == 403
    assert response.json()["data"]["service"] == "tos"
    assert response.json()["data"]["category"] == "permission"
    assert all(not sdk.pre_signed_url.called for sdk in api.sdk_clients)


@pytest.mark.parametrize("mode", ["text", "image"])
async def test_saved_legacy_model_rejected_before_cloud_calls(api, mode):
    async with api.sessions() as session:
        saved = await session.scalar(select(UserSystemSettings).where(
            UserSystemSettings.user_id == "user-1",
        ))
        saved.embedding_model = "legacy"
        await session.commit()
    response = await search(api, mode)
    assert response.status_code == 409
    assert not api.requests
    api.milvus.search.assert_not_awaited()


@pytest.mark.parametrize("mode", ["text", "image"])
@pytest.mark.parametrize("operation", ["get_collection_config", "search"])
async def test_milvus_disconnect_is_error_not_empty_result(api, mode, operation):
    getattr(api.milvus, operation).side_effect = RuntimeError("PRIVATE?Signature=secret")
    response = await search(api, mode)
    assert response.status_code == 503
    assert response.json()["data"]["service"] == "milvus"
    assert "PRIVATE" not in response.text and "Signature" not in response.text
    async with api.sessions() as session:
        assert (await session.execute(select(SearchHistory))).scalars().all() == []


@pytest.mark.parametrize("mode", ["text", "image"])
async def test_ark_failure_is_sanitized(api, mode):
    api.ark_handler.side_effect = lambda request: httpx.Response(
        401, json={"error": {"message": "PRIVATE CREDENTIAL"}},
        headers={"x-request-id": "offline-request"},
    )
    response = await search(api, mode)
    assert response.status_code == 401
    assert response.json()["data"]["service"] == "ark"
    assert "PRIVATE" not in response.text
    api.milvus.search.assert_not_awaited()


@pytest.mark.parametrize("mode", ["text", "image", "tags"])
async def test_rds_disconnect_is_error_not_empty_result(api, mode, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise OperationalError("PRIVATE SQL", {}, Exception("PRIVATE CREDENTIAL"))

    monkeypatch.setattr(search_module.search_service, "_fetch_tags_by_ids", unavailable)
    response = await search(api, mode)
    assert response.status_code == 503
    assert response.json()["data"]["service"] == "mysql"
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("score", [float("nan"), float("inf"), None, "0.5"])
async def test_invalid_milvus_score_is_error(api, score):
    api.milvus.search.return_value[0]["score"] = score
    response = await search(api, "text")
    assert response.status_code == 502


async def test_manual_tag_edit_remains_visible_in_all_search_modes(api):
    response = await api.client.put("/api/tags/media/media-0", json={
        "tags": [{
            "source": "default", "category": "road",
            "name": "\u9ad8\u901f\u516c\u8def",
        }],
    })
    assert response.status_code == 200
    for mode in ("text", "image", "tags"):
        kwargs = {"tags": [{
            "source": "default", "category": "road",
            "name": "\u9ad8\u901f\u516c\u8def",
        }]} if mode == "tags" else {}
        result = (await search(api, mode, **kwargs)).json()["data"]["items"]
        media = next(item for item in result if item["media_id"] == "media-0")
        assert media["tags"] == [{
            "source": "default",
            "category": "road", "tag_name": "\u9ad8\u901f\u516c\u8def",
            "confidence": 1.0, "is_manual": True,
        }]


@pytest.mark.parametrize("mime,content", [
    ("text/plain", IMAGE), ("image/png", b""), ("image/png", b"x" * (10 * 1024 * 1024)),
])
async def test_invalid_upload_returns_400_and_closes_file(api, mime, content, monkeypatch):
    # Multipart creates Starlette's base class directly with current FastAPI.
    from starlette.datastructures import UploadFile as StarletteUploadFile
    original = StarletteUploadFile.close
    closed = []

    async def close(upload):
        closed.append(upload)
        await original(upload)

    monkeypatch.setattr(StarletteUploadFile, "close", close)
    response = await api.client.post(
        "/api/search/image", files={"image": ("image.png", content, mime)},
    )
    assert response.status_code == 400
    assert closed and all(upload.file.closed for upload in closed)
    assert not api.requests


@pytest.mark.parametrize("params", [
    {"threshold": -0.1}, {"threshold": 1.1}, {"threshold": "nan"},
    {"top_k": 0}, {"top_k": 101},
])
async def test_image_form_constraints(api, params):
    response = await search(api, "image", **params)
    assert response.status_code == 422
    assert not api.requests


async def test_history_removes_signed_query_and_data_uri(api):
    response = await search(
        api, "text", query="find https://bucket.invalid/x?X-Tos-Signature=secret data:image/png;base64,c2VjcmV0",
    )
    assert response.status_code == 200
    async with api.sessions() as session:
        history = (await session.execute(select(SearchHistory))).scalar_one()
        assert history.query_content == "find https://bucket.invalid/x [redacted media]"


@pytest.mark.parametrize("mode", ["text", "image", "tags"])
async def test_true_empty_search_is_success(api, mode):
    api.milvus.search.return_value = []
    kwargs = {"tags": [{
        "source": "default", "category": "road", "name": "missing",
    }]} if mode == "tags" else {}
    response = await search(api, mode, **kwargs)
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0
    assert response.json()["data"]["items"] == []


@pytest.mark.parametrize("mode", ["text", "image"])
async def test_search_without_user_key_does_not_use_deployment_key(api, mode):
    async with api.sessions() as session:
        row = await session.scalar(select(UserSystemSettings).where(
            UserSystemSettings.user_id == "user-1",
        ))
        row.ark_api_key = None
        await session.commit()
    response = await search(api, mode)
    assert response.status_code == 503
    assert response.json()["data"]["category"] == "not_configured"
    api.ark_handler.assert_not_called()
    api.milvus.search.assert_not_awaited()


async def test_tag_pagination_reaches_all_results_above_default_limit(api):
    async with api.sessions() as session:
        for index in range(25):
            media_id = f"extra-{index:02}"
            session.add(MediaFile(
                id=media_id, user_id="user-1", tos_url=f"tos://user-bucket/{media_id}.png",
                file_type="image", file_name=f"{media_id}.png",
            ))
            session.add(MediaTag(
                user_id="user-1", media_id=media_id, source="default",
                category="road", tag_name="highway",
            ))
        await session.commit()
    ids = []
    for page, count in [(1, 12), (2, 12), (3, 4)]:
        response = await search(api, "tags", page=page, size=12)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 28 and data["page"] == page
        assert len(data["items"]) == count
        ids.extend(item["media_id"] for item in data["items"])
    assert len(set(ids)) == 28
    assert "media-other" not in ids
