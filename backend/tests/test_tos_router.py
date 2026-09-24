"""Proxy tests load only the owned router, independently of other migrations."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.errors import ServiceError
from app.services.tos_service import TOSService
from app.utils.helpers import build_tos_url


@pytest.fixture
def router_module():
    path = Path(__file__).resolve().parents[1] / "app/api/tos_router.py"
    spec = importlib.util.spec_from_file_location("isolated_tos_router", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stream:
    def __init__(self, status=200, headers=None, body=b"abc"):
        self.status_code = status
        self.headers = headers or {"content-type": "video/mp4", "content-length": "3"}
        self.body = body
        self.closed = False
        self.iterated = False

    async def aiter_bytes(self):
        self.iterated = True
        yield self.body

    async def aclose(self):
        self.closed = True


def client_for(module, monkeypatch, stream):
    service = SimpleNamespace(
        bucket_name="sample", open_object=AsyncMock(return_value=stream),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(
        TOSService, "from_settings", lambda values: service,
    )
    media = SimpleNamespace(user_id="user-1")
    session = SimpleNamespace(scalar=AsyncMock(return_value=media))
    app = FastAPI()
    app.include_router(module.router, prefix="/api")
    app.dependency_overrides[module.get_current_user] = lambda: {
        "id": "user-1", "role": "user", "is_demo": 0,
    }
    app.dependency_overrides[module.get_user_settings] = lambda: {
        "tos_bucket_name": "sample",
    }
    app.dependency_overrides[module.get_session] = lambda: session
    return TestClient(app), service


@pytest.mark.parametrize("status", [200, 206])
def test_streaming_content_headers_and_range(router_module, monkeypatch, status):
    headers = {
        "Content-Type": "video/mp4", "Content-Length": "3",
        "Content-Range": "bytes 0-2/10", "ETag": '"test"',
        "Last-Modified": "Wed, 16 Sep 2026 10:00:00 GMT",
        "Content-Encoding": "identity",
    }
    stream = Stream(status=status, headers=headers)
    client, service = client_for(router_module, monkeypatch, stream)
    with client:
        response = client.get("/api/tos/sample/video.mp4", headers={"Range": "bytes=0-2"})
    assert response.status_code == status
    assert response.content == b"abc"
    for key, value in headers.items():
        assert response.headers[key] == value
    assert response.headers["cache-control"] == "private, no-store"
    assert stream.closed
    service.open_object.assert_awaited_once_with(
        "tos://sample/video.mp4", method="GET", range_header="bytes=0-2",
    )


def test_head_does_not_iterate_body(router_module, monkeypatch):
    stream = Stream(headers={"Content-Length": "999", "Content-Type": "image/jpeg"})
    client, service = client_for(router_module, monkeypatch, stream)
    with client:
        response = client.head("/api/tos/sample/image.jpg")
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "999"
    assert stream.closed and not stream.iterated
    assert service.open_object.call_args.kwargs["method"] == "HEAD"


@pytest.mark.parametrize("method", ["get", "head"])
@pytest.mark.parametrize("status", [403, 404, 416])
def test_upstream_error_status_and_range_not_converted_to_500(
    router_module, monkeypatch, method, status,
):
    stream = Stream(status, {
        "Content-Range": "bytes */99", "Content-Length": "999",
        "Content-Type": "application/xml",
    }, body=b"XML with private details")
    client, service = client_for(router_module, monkeypatch, stream)
    with client:
        response = getattr(client, method)("/api/tos/sample/file.mp4")
    assert response.status_code == status
    assert response.headers["content-range"] == "bytes */99"
    assert response.content == b""
    assert stream.closed and not stream.iterated
    assert response.headers["content-length"] == ("999" if method == "head" else "0")


@pytest.mark.asyncio
async def test_proxy_decodes_special_key_once(router_module, monkeypatch):
    key = "\u4e2d\u6587/space +%# literal%20.mp4"
    stream = Stream()
    client, service = client_for(router_module, monkeypatch, stream)
    # Starlette's legacy httpx TestClient transport unquotes URL.path twice.
    # ASGITransport matches the once-decoded scope supplied by ASGI servers.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client.app), base_url="http://testserver",
    ) as http:
        response = await http.get(f"/api/tos/sample/{quote(key, safe='/')}")
    assert response.status_code == 200
    assert service.open_object.call_args.args == (build_tos_url("sample", key),)
    assert "filename*=UTF-8''space%20%2B%25%23%20literal%2520.mp4" == (
        response.headers["content-disposition"].split("; ")[1]
    )
    assert stream.closed


def test_wrong_bucket_rejected_before_open(router_module, monkeypatch):
    client, service = client_for(router_module, monkeypatch, Stream())
    with client:
        response = client.get("/api/tos/other/file.jpg")
    assert response.status_code == 403
    service.open_object.assert_not_called()


@pytest.mark.parametrize("status", [400, 403, 404, 503])
def test_service_errors_preserve_safe_status(router_module, monkeypatch, status):
    client, service = client_for(router_module, monkeypatch, Stream())
    service.open_object.side_effect = ServiceError("tos", "unavailable", status_code=status)
    with client:
        response = client.get("/api/tos/sample/file.jpg")
    assert response.status_code == status
    assert response.json()["detail"]["service"] == "tos"


@pytest.mark.asyncio
async def test_response_closes_stream_when_asgi_send_fails(router_module):
    stream = Stream()
    resources = SimpleNamespace(aclose=AsyncMock())
    response = router_module._ProxyResponse(stream, resources=resources)

    async def send(message):
        raise RuntimeError("browser disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "GET"}
    with pytest.raises(RuntimeError, match="browser disconnected"):
        await response(scope, receive, send)
    assert stream.closed
    resources.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_response_closes_stream_on_iteration_error(router_module):
    class BrokenStream(Stream):
        async def aiter_bytes(self):
            yield b"a"
            raise RuntimeError("upstream reset")

    stream = BrokenStream()
    resources = SimpleNamespace(aclose=AsyncMock())
    response = router_module._ProxyResponse(stream, resources=resources)

    async def send(message):
        pass

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(RuntimeError, match="upstream reset"):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert stream.closed
    resources.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_proxy_keeps_client_lease_until_response_finishes(router_module, monkeypatch):
    import app.services.tos_service as pool

    stream = Stream()
    _, service = client_for(router_module, monkeypatch, stream)
    response = await router_module.proxy_tos_file(
        SimpleNamespace(method="GET", headers={}),
        "sample", "image.jpg",
        {"id": "user-1", "role": "user"},
        {"tos_bucket_name": "sample"},
        SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(user_id="user-1"))),
    )
    assert pool._leases[id(service)][1] == 1
    service.aclose.assert_not_awaited()

    async def send(message):
        assert id(service) in pool._leases

    async def receive():
        return {"type": "http.disconnect"}

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert id(service) not in pool._leases
    service.aclose.assert_awaited_once()
    assert stream.closed
