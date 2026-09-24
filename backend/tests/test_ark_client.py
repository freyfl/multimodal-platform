import asyncio
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from app.errors import ServiceError
from app.services.ark_client import ArkClient, media_kind, validate_media_url
from app.services.embedding_service import EmbeddingService
from app.services.tag_service import TagService


@pytest.fixture
def config(empty_settings):
    return empty_settings.model_copy(update={
        "ARK_API_KEY": "offline-test-key", "ARK_MAX_RETRIES": 2,
        "ARK_RETRY_BASE_DELAY": 0.001, "ARK_RETRY_MAX_DELAY": 30,
    })


@pytest.mark.parametrize("status,category,retryable,calls", [
    (400, "invalid_request", False, 1), (401, "authentication", False, 1),
    (403, "permission", False, 1), (404, "not_found", False, 1),
    (422, "invalid_request", False, 1), (429, "rate_limit", True, 3),
    (408, "timeout", True, 3), (500, "unavailable", True, 3),
    (502, "unavailable", True, 3), (503, "unavailable", True, 3),
    (504, "unavailable", True, 3), (501, "unavailable", False, 1),
])
async def test_http_errors_are_bounded_and_redacted(config, status, category, retryable, calls):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "SECRET signature=SECRET"}},
                              headers={"x-request-id": "req-123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ArkClient(config=config, http_client=http)
        with pytest.raises(ServiceError) as captured:
            await client.post("/responses", {"model": config.ARK_TAG_MODEL})
        error = captured.value
        assert (error.category, error.retryable, error.request_id) == (category, retryable, "req-123")
        assert len(requests) == calls
        assert "SECRET" not in str(error) + json.dumps(error.to_dict())
        assert error.__suppress_context__
        assert all(r.url.path == "/api/v3/responses" for r in requests)


@pytest.mark.parametrize("retry_after", ["2", "date"])
async def test_retry_after_then_success(config, monkeypatch, retry_after):
    if retry_after == "date":
        retry_after = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=3), usegmt=True)
    responses = [
        httpx.Response(429, headers={"Retry-After": retry_after}),
        httpx.Response(200, json={"id": "ok"}),
    ]
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.ark_client.asyncio.sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: responses.pop(0))) as http:
        client = ArkClient(config=config, http_client=http)
        assert await client.post("/responses", {}) == {"id": "ok"}
    assert len(responses) == 0
    assert 1.5 <= sleep.call_args.args[0] <= 3


async def test_long_retry_after_does_not_retry_early(config):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(503, headers={"Retry-After": "3600"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ServiceError) as captured:
            await ArkClient(config=config, http_client=http).post("/responses", {})
    assert count == 1
    assert captured.value.retryable


@pytest.mark.parametrize("header", ["invalid", "NaN", "inf", "-20"])
def test_invalid_retry_after_uses_finite_backoff(config, header):
    assert ArkClient(config=config)._retry_delay(1, header) == 0.002


@pytest.mark.parametrize("exception,category", [
    (httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "unavailable"),
])
async def test_transport_errors_are_retried_without_leaking(config, exception, category):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        raise exception("SECRET signed_url?signature=SECRET", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ServiceError) as captured:
            await ArkClient(config=config, http_client=http).post("/responses", {})
    assert count == 3
    assert captured.value.category == category
    assert "SECRET" not in str(captured.value)
    assert captured.value.__suppress_context__


async def test_total_attempt_timeout(config):
    config.ARK_REQUEST_TIMEOUT = 0.01
    config.ARK_MAX_RETRIES = 0

    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ServiceError) as captured:
            await ArkClient(config=config, http_client=http).post("/responses", {})
        assert captured.value.category == "timeout"


async def test_concurrency_and_per_request_credentials(config):
    config.ARK_MAX_CONCURRENCY = 2
    active = peak = 0
    keys = []

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        keys.append(request.headers["authorization"])
        assert request.extensions["timeout"]["read"] == config.ARK_REQUEST_TIMEOUT
        await asyncio.sleep(0.002)
        active -= 1
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ArkClient(config=config, http_client=http)
        await asyncio.gather(*(
            client.post("/responses" if i % 2 else "/embeddings/multimodal", {},
                        api_key=f"user-{i}") for i in range(8)
        ))
        assert peak == 2
        assert sorted(keys) == [f"Bearer user-{i}" for i in range(8)]
        assert "authorization" not in http.headers


async def test_cancellation_releases_concurrency_slot(config):
    config.ARK_MAX_CONCURRENCY = 1
    entered = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await asyncio.Event().wait()
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ArkClient(config=config, http_client=http)
        task = asyncio.create_task(client.post("/responses", {}))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.wait_for(client.post("/responses", {}), timeout=1) == {}
        assert calls == 2


@pytest.mark.parametrize("body", [
    b"[]", b"null", b"not json SECRET", b'{"error":{"message":"SECRET"}}',
    b'{"x":NaN}', b'{"id":"a","id":"b"}', b'{"model":"different-model"}',
])
async def test_invalid_envelopes_never_retry(config, body):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, content=body, headers={"x-request-id": "response-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ServiceError) as captured:
            await ArkClient(config=config, http_client=http).post("/responses", {"model": "expected"})
    assert count == 1
    assert captured.value.category == "invalid_response"
    assert captured.value.request_id == "response-1"
    assert "SECRET" not in str(captured.value)


async def test_redirect_is_not_followed(config):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://other.invalid/SECRET"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as http:
        with pytest.raises(ServiceError):
            await ArkClient(config=config, http_client=http).post("/responses", {})
    assert len(calls) == 1


async def test_lazy_missing_config_and_owned_lifecycle(empty_settings, config, monkeypatch):
    client = ArkClient(config=empty_settings)
    assert client._client is None
    with pytest.raises(ServiceError) as captured:
        await client.post("/responses", {})
    assert captured.value.category == "not_configured"
    assert client._client is None
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    monkeypatch.setattr("app.services.ark_client.httpx.AsyncClient", lambda **kw: http)
    owned = ArkClient(config=config)
    await owned.post("/responses", {})
    await owned.aclose()
    await owned.aclose()
    assert http.is_closed
    with pytest.raises(ServiceError):
        await owned.post("/responses", {})


async def test_injected_http_client_is_borrowed(config):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as http:
        client = ArkClient(config=config, http_client=http)
        await client.aclose()
        assert not http.is_closed


@pytest.mark.parametrize("service_type", [EmbeddingService, TagService])
async def test_service_owned_client_closes(config, service_type):
    service = service_type(config=config)
    service._client.aclose = AsyncMock()
    await service.aclose()
    service._client.aclose.assert_awaited_once()


async def test_shared_service_lifecycle_closes_owned_transport(config, monkeypatch):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    monkeypatch.setattr("app.services.ark_client.httpx.AsyncClient", lambda **kw: http)
    client = ArkClient(config=config)
    embedding = EmbeddingService(client=client)
    tags = TagService(client=client)
    await client.post("/responses", {})
    await embedding.aclose()
    await tags.aclose()
    assert http.is_closed


@pytest.mark.parametrize("key", ["", " ", "SECRET\nheader", "nonascii-\u4e2d"])
async def test_invalid_key_never_reaches_transport(config, key):
    client = ArkClient(config=config)
    with pytest.raises(ServiceError) as captured:
        await client.post("/responses", {}, api_key=key)
    assert client._client is None
    assert "SECRET" not in str(captured.value)


def test_service_construction_never_allocates_http_client(empty_settings, monkeypatch):
    def deny(**kwargs):
        raise AssertionError("HTTP client must be lazy")

    monkeypatch.setattr("app.services.ark_client.httpx.AsyncClient", deny)
    assert EmbeddingService(config=empty_settings)._client._client is None
    assert TagService(config=empty_settings)._client._client is None


@pytest.mark.parametrize("url", [
    "tos://bucket/image.png", "file:///tmp/image.png", "http://host.invalid/image.png",
    "https://user:password@host.invalid/image.png", "data:image/png;base64,",
    "data:image/png;base64,%%%%", "data:text/plain;base64,QQ==",
    "data:video/mp4;base64,QQ==", "https://host.invalid/\nimage.png", None,
])
def test_invalid_image_sources_are_safe(url):
    with pytest.raises(ServiceError) as captured:
        validate_media_url(url, "image")
    assert captured.value.category == "invalid_request"
    assert "password" not in str(captured.value)


@pytest.mark.parametrize("url,kind", [
    ("tos://bucket/clip.MP4", "video"),
    ("tos://bucket/name%23%3F.MOV", "video"),
    ("https://host.invalid/clip.avi?signature=SECRET", "video"),
    ("tos://bucket/photo.png", "image"),
])
def test_media_modality(url, kind):
    assert media_kind(url) == kind


@pytest.mark.parametrize("url", ["tos://bucket/a.mkv", "tos://bucket/a.txt", "", None])
def test_unsupported_media_is_explicit(url):
    with pytest.raises(ServiceError):
        media_kind(url)
