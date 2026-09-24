"""Offline TOS tests use the real SDK signatures and fake credentials only."""

import asyncio
import inspect
import threading
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx
import pytest
import tos
from tos.enum import HttpMethodType
from tos.models2 import ListObjectType2Output

from app.errors import MissingConfigurationError, ServiceError
from app.services.tos_service import TOSService
from app.utils.helpers import build_tos_url, parse_tos_url


CONFIG = {
    "access_key_id": "offline-ak", "access_key_secret": "offline-secret",
    "bucket_name": "sample", "endpoint": "tos-cn-beijing.example.invalid",
    "region": "cn-beijing", "security_token": "", "custom_domain": "",
}
KEY = "\u4e2d\u6587/space +%# literal%20.mp4"


@pytest.fixture
def sdk():
    return create_autospec(tos.TosClientV2, instance=True)


@pytest.fixture
def service(sdk):
    return TOSService(**CONFIG, client=sdk, max_workers=2)


@pytest.mark.parametrize("key", ["", "prefix/", KEY, "/leading//slash.png", "a?b.jpg", "%2F.png"])
def test_uri_round_trip(key):
    uri = build_tos_url("sample", key)
    assert parse_tos_url(uri) == {
        "bucket": "sample", "path": key, "filename": key.rsplit("/", 1)[-1],
    }
    assert build_tos_url("sample", parse_tos_url(uri)["path"]) == uri
    assert " " not in uri and "+" not in uri and "#" not in uri


def test_unescaped_directory_characters_and_percent_are_supported():
    assert parse_tos_url("tos://sample/\u4e2d\u6587 +%#/")["path"] == "\u4e2d\u6587 +%#/"


@pytest.mark.parametrize("uri", [
    "oss://sample/key", "https://sample.invalid/key?signature=secret",
    "tos://sample.invalid/key", "tos://user@sample/key", "tos://sample:443/key",
    "tos://SAMPLE/key", "tos:///key", "tos://sample/%00.jpg",
    "tos://sample/\n.jpg", "tos://sample/%FF.jpg",
])
def test_invalid_uri_rejected(uri):
    assert parse_tos_url(uri) is None


def page(keys, *, truncated=False, token=None):
    response = SimpleNamespace(
        request_id="offline-request", status=200, headers={},
        json_read=lambda: {
            "Name": "sample", "EncodingType": "url",
            "IsTruncated": truncated, "NextContinuationToken": token,
            "Contents": [{"Key": quote(key, safe="/"), "Size": 12} for key in keys],
        },
    )
    return ListObjectType2Output(response)


@pytest.mark.asyncio
async def test_paginated_list_uses_real_sdk_output(service, sdk):
    sdk.list_objects_type2.side_effect = [
        page(["prefix/", "prefix/readme.txt", f"prefix/{KEY}"], truncated=True, token="opaque+/="),
        page(["prefix/image.JPG"]),
    ]
    try:
        files = await service.list_files("tos://sample/prefix")
        assert [item["file_type"] for item in files] == ["video", "image"]
        assert files[0]["tos_url"] == build_tos_url("sample", f"prefix/{KEY}")
        assert files[0]["file_name"] == KEY.rsplit("/", 1)[-1]
        assert files[0]["file_size"] == 12
        calls = sdk.list_objects_type2.call_args_list
        assert calls[0].kwargs == {
            "bucket": "sample", "prefix": "prefix/", "max_keys": 1000,
            "continuation_token": None, "list_only_once": True, "encoding_type": "url",
        }
        assert calls[1].kwargs["continuation_token"] == "opaque+/="
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_empty_directory(service, sdk):
    sdk.list_objects_type2.return_value = page([])
    try:
        assert await service.list_files("tos://sample/") == []
        assert sdk.list_objects_type2.call_args.kwargs["prefix"] == ""
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_broken_pagination_fails_instead_of_looping(service, sdk):
    sdk.list_objects_type2.return_value = page([], truncated=True, token="same")
    try:
        with pytest.raises(ServiceError) as captured:
            await service.list_files("tos://sample/")
        assert captured.value.category == "invalid_response"
        assert sdk.list_objects_type2.call_count == 2
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_bucket_mismatch_on_every_object_operation(service, sdk):
    operations = [
        service.list_files("tos://other/"), service.file_exists("tos://other/a"),
        service.get_file_url("tos://other/a"), service.get_preview_url("tos://other/a"),
        service.upload_file("/unused", "tos://other/a"),
        service.download_file("tos://other/a", "/unused"),
        service.delete_file("tos://other/a"), service.open_object("tos://other/a"),
    ]
    try:
        for operation in operations:
            with pytest.raises(ServiceError) as captured:
                await operation
            assert captured.value.status_code == 403
        assert not sdk.method_calls
        assert service._executor is None
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_missing_config_is_lazy_and_does_not_construct_client():
    factory = Mock()
    service = TOSService(**{**CONFIG, "access_key_id": ""}, client_factory=factory)
    assert service._executor is None
    try:
        with pytest.raises(MissingConfigurationError) as captured:
            await service.list_files("tos://sample/")
        assert captured.value.missing_fields == ("TOS_ACCESS_KEY_ID",)
        factory.assert_not_called()
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_sdk_construction_and_close_are_lazy_off_event_loop(sdk):
    main_thread = threading.get_ident()
    threads = []

    def factory(**kwargs):
        threads.append(threading.get_ident())
        assert kwargs["endpoint"].startswith("https://")
        assert kwargs["security_token"] == "offline-token"
        return sdk

    service = TOSService(**{**CONFIG, "security_token": "offline-token"}, client_factory=factory)
    assert threads == []
    await service.check_connection()
    await service.aclose()
    await service.aclose()
    assert len(threads) == 1 and threads[0] != main_thread
    sdk.close.assert_called_once()
    with pytest.raises(ServiceError):
        await service.check_connection()


@pytest.mark.asyncio
async def test_upload_download_delete_pass_raw_key_and_bucket(service, sdk):
    uri = build_tos_url("sample", KEY)
    try:
        assert await service.upload_file("/local/input", uri)
        assert await service.download_file(uri, "/local/output")
        assert await service.delete_file(uri) is None
        sdk.put_object_from_file.assert_called_once_with(
            bucket="sample", key=KEY, file_path="/local/input",
        )
        sdk.get_object_to_file.assert_called_once_with(
            bucket="sample", key=KEY, file_path="/local/output",
        )
        sdk.delete_object.assert_called_once_with(bucket="sample", key=KEY)
    finally:
        await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 416, 500])
async def test_exists_only_hides_404_and_errors_are_redacted(service, sdk, status):
    error = RuntimeError("secret query ?X-Tos-Signature=do-not-leak")
    error.status_code = status
    error.request_id = "request-123"
    sdk.head_object.side_effect = error
    try:
        if status == 404:
            assert await service.file_exists("tos://sample/a") is False
        else:
            with pytest.raises(ServiceError) as captured:
                await service.file_exists("tos://sample/a")
            assert captured.value.status_code == status
            assert captured.value.request_id == "request-123"
            assert "do-not-leak" not in str(captured.value.to_dict())
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_real_sdk_signature_encoding_and_custom_domain_without_network():
    client = tos.TosClientV2(
        ak="offline-ak", sk="offline-secret", endpoint="https://tos-cn-beijing.example.invalid",
        region="cn-beijing", dns_cache_time=0,
    )
    service = TOSService(
        **{**CONFIG, "custom_domain": "media.example.invalid"}, client=client,
    )
    try:
        uri = build_tos_url("sample", KEY)
        standard = urlsplit(await service.get_file_url(uri, expires=60))
        preview = urlsplit(await service.get_preview_url(uri, expires=60))
        assert standard.scheme == preview.scheme == "https"
        assert standard.hostname == "sample.tos-cn-beijing.example.invalid"
        assert preview.hostname == "media.example.invalid"
        assert unquote(standard.path[1:]) == unquote(preview.path[1:]) == KEY
        assert "%2520" in standard.path
        assert "X-Tos-Signature" in parse_qs(standard.query)
        assert parse_qs(standard.query)["X-Tos-Expires"] == ["60"]
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_older_sdk_custom_signing_falls_back_to_standard_domain():
    class OlderSigner:
        def pre_signed_url(self, http_method, bucket, key, expires):
            assert http_method == HttpMethodType.Http_Method_Get
            return SimpleNamespace(signed_url="https://sample.standard.invalid/a?signature=opaque")

        def close(self):
            pass

    service = TOSService(
        **{**CONFIG, "custom_domain": "media.example.invalid"}, client=OlderSigner(),
    )
    try:
        assert await service.get_preview_url("tos://sample/a") == (
            "https://sample.standard.invalid/a?signature=opaque"
        )
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_cancelled_calls_do_not_release_worker_slots_early(sdk):
    service = TOSService(**CONFIG, client=sdk, max_workers=1)
    started, release = threading.Event(), threading.Event()

    def blocked(**kwargs):
        started.set()
        assert release.wait(5)

    sdk.head_object.side_effect = blocked
    first = asyncio.create_task(service.file_exists("tos://sample/a"))
    while not started.is_set():
        await asyncio.sleep(0.001)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(service.file_exists("tos://sample/b"))
    try:
        await asyncio.sleep(0.03)
        assert sdk.head_object.call_count == 1
        assert service._executor._work_queue.qsize() == 0
    finally:
        release.set()
        await second
        await service.aclose()


@pytest.mark.asyncio
async def test_close_waits_for_running_sdk_call(sdk):
    service = TOSService(**CONFIG, client=sdk, max_workers=1)
    started, release = threading.Event(), threading.Event()
    sdk.head_object.side_effect = lambda **kwargs: (started.set(), release.wait(5))
    call = asyncio.create_task(service.file_exists("tos://sample/a"))
    while not started.is_set():
        await asyncio.sleep(0.001)
    close = asyncio.create_task(service.aclose())
    try:
        await asyncio.sleep(0.02)
        assert not close.done()
        sdk.close.assert_not_called()
    finally:
        release.set()
        await call
        await close
    sdk.close.assert_called_once()


@pytest.mark.asyncio
async def test_custom_instances_never_borrow_partial_global_credentials(monkeypatch):
    import app.services.tos_service as module

    monkeypatch.setattr(module, "_instance_cache", {})
    with pytest.raises(MissingConfigurationError):
        TOSService.from_settings({"is_custom": False})
    configured = {"is_custom": True, **{f"tos_{key}": value for key, value in CONFIG.items()}}
    custom = TOSService.from_settings(configured)
    try:
        assert custom is TOSService.from_settings(configured)
        with pytest.raises(MissingConfigurationError):
            TOSService.from_settings({"is_custom": True, "tos_bucket_name": "other"})
        assert list(module._instance_cache.values()) == [custom]
    finally:
        await custom.aclose()


def test_service_matches_frozen_contract():
    from app.services.contracts import TOSContract

    for name, method in vars(TOSContract).items():
        if name.startswith("_") or name == "from_settings":
            continue
        assert hasattr(TOSService, name)
        assert inspect.iscoroutinefunction(getattr(TOSService, name))
        assert list(inspect.signature(method).parameters) == list(
            inspect.signature(getattr(TOSService, name)).parameters
        )


class WireStream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield b"abc"

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_open_object_signs_method_and_preserves_http_stream(method, sdk):
    sdk.pre_signed_url.return_value = SimpleNamespace(
        signed_url="https://sample.example.invalid/a?opaque=a%2Bb%25%23",
    )
    wire = WireStream()

    def handle(request):
        assert request.method == method
        assert request.headers["range"] == "bytes=0-2"
        assert request.url.query == b"opaque=a%2Bb%25%23"
        return httpx.Response(206, headers={"Content-Range": "bytes 0-2/10"}, stream=wire)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    service = TOSService(**CONFIG, client=sdk, http_client=http)
    try:
        stream = await service.open_object("tos://sample/a", method=method, range_header="bytes=0-2")
        assert stream.status_code == 206
        assert stream.headers["content-range"] == "bytes 0-2/10"
        if method == "GET":
            assert b"".join([chunk async for chunk in stream.aiter_bytes()]) == b"abc"
        else:
            await stream.aclose()
        assert wire.closed
        assert sdk.pre_signed_url.call_args.kwargs["http_method"] == (
            HttpMethodType.Http_Method_Head if method == "HEAD" else HttpMethodType.Http_Method_Get
        )
    finally:
        await service.aclose()
    assert http.is_closed


@pytest.mark.asyncio
async def test_service_close_releases_unconsumed_http_stream(sdk):
    sdk.pre_signed_url.return_value = SimpleNamespace(
        signed_url="https://sample.example.invalid/a?signature=offline",
    )
    wire = WireStream()
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=wire),
    ))
    service = TOSService(**CONFIG, client=sdk, http_client=http)
    await service.open_object("tos://sample/a")
    assert not wire.closed
    await service.aclose()
    assert wire.closed and http.is_closed and not service._streams
    sdk.close.assert_called_once()


@pytest.mark.asyncio
async def test_cancelled_stream_close_still_finishes(sdk):
    sdk.pre_signed_url.return_value = SimpleNamespace(
        signed_url="https://sample.example.invalid/a?signature=offline",
    )
    started, release = asyncio.Event(), asyncio.Event()

    class SlowClose(WireStream):
        async def aclose(self):
            started.set()
            await release.wait()
            await super().aclose()

    wire = SlowClose()
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=wire),
    ))
    service = TOSService(**CONFIG, client=sdk, http_client=http)
    stream = await service.open_object("tos://sample/a")
    close = asyncio.create_task(stream.aclose())
    await started.wait()
    close.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await close
    finally:
        release.set()
        await service.aclose()
    assert wire.closed and not service._streams


@pytest.mark.asyncio
async def test_lifespan_hook_closes_global_and_cached_instances(monkeypatch, sdk):
    import app.services.tos_service as module

    global_service = TOSService(**CONFIG, client=sdk)
    custom_sdk = create_autospec(tos.TosClientV2, instance=True)
    custom_service = TOSService(**CONFIG, client=custom_sdk)
    monkeypatch.setattr(module, "tos_service", global_service)
    monkeypatch.setattr(module, "_instance_cache", {("offline",): custom_service})
    await module.close_tos_services()
    assert module._instance_cache == {}
    sdk.close.assert_called_once()
    custom_sdk.close.assert_called_once()


@pytest.mark.asyncio
async def test_cache_recycles_more_than_64_configs_without_closing_a_borrower(monkeypatch):
    import app.services.tos_service as module

    monkeypatch.setattr(module, "_instance_cache", {})
    monkeypatch.setattr(module, "_leases", {})
    monkeypatch.setattr(module, "tos_service", TOSService(**CONFIG))
    clients = []

    def factory(**kwargs):
        client = Mock()
        clients.append(client)
        return client

    monkeypatch.setattr(tos, "TosClientV2", factory)
    base = {f"tos_{key}": value for key, value in CONFIG.items()}
    async with module.borrow_tos(base) as pinned:
        await pinned.check_connection()
        for index in range(70):
            async with module.borrow_tos({**base, "tos_access_key_id": f"user-{index}"}) as service:
                await service.check_connection()
            assert len(module._instance_cache) <= 64
        # Idle between operations does not mean the import released its client.
        assert not pinned._closed
        clients[0].close.assert_not_called()
        await pinned.check_connection()
    if module._closing_tasks:
        await asyncio.gather(*tuple(module._closing_tasks))
    assert any(client.close.called for client in clients[1:])
    await module.close_tos_services()
    for client in clients:
        client.close.assert_called_once()


@pytest.mark.asyncio
async def test_full_busy_cache_uses_temporary_client_and_releases_on_cancel(monkeypatch):
    import app.services.tos_service as module

    monkeypatch.setattr(module, "_instance_cache", {})
    monkeypatch.setattr(module, "_leases", {})
    monkeypatch.setattr(module, "tos_service", TOSService(**CONFIG))
    monkeypatch.setattr(module, "_CACHE_LIMIT", 1)
    base = {f"tos_{key}": value for key, value in CONFIG.items()}
    entered, release = asyncio.Event(), asyncio.Event()
    temporary = []

    async def borrow_overflow():
        async with module.borrow_tos({**base, "tos_access_key_id": "other"}) as service:
            temporary.append(service)
            entered.set()
            await release.wait()

    async with module.borrow_tos(base) as pinned:
        task = asyncio.create_task(borrow_overflow())
        await entered.wait()
        assert not pinned._closed and not temporary[0]._closed
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert temporary[0]._closed
        assert list(module._instance_cache.values()) == [pinned]
    await module.close_tos_services()
    assert not module._leases


@pytest.mark.asyncio
async def test_invalid_configs_do_not_consume_cache_capacity(monkeypatch):
    import app.services.tos_service as module

    monkeypatch.setattr(module, "_instance_cache", {})
    for index in range(70):
        with pytest.raises(MissingConfigurationError):
            TOSService.from_settings({"tos_bucket_name": f"bucket-{index}"})
    assert module._instance_cache == {}
