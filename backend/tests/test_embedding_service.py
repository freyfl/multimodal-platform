import base64
import json

import httpx
import pytest

from app.errors import ServiceError, VectorSpaceMismatchError
from app.services.ark_client import ArkClient
from app.services.embedding_service import EmbeddingService
from app.vector_space import (
    ARK_EMBEDDING_MODEL, IMAGE_CORPUS_INSTRUCTION, IMAGE_QUERY_INSTRUCTION,
    TEXT_QUERY_INSTRUCTION, VIDEO_CORPUS_INSTRUCTION,
)


VECTOR = [0.125, -0.5] + [0.0] * 1022
# Protocol fixture only; a real image is not sent to any model.
IMAGE = "data:image/png;base64," + base64.b64encode(b"offline-image").decode()
SIGNED = "https://bucket.invalid/media?X-Tos-Signature=offline%2Btest"


def service(http, empty_settings):
    return EmbeddingService(client=ArkClient(
        config=empty_settings.model_copy(update={"ARK_API_KEY": "offline-key"}),
        http_client=http,
    ))


@pytest.mark.parametrize("operation,args,instruction,item", [
    ("embed_text", (" original text ",), TEXT_QUERY_INSTRUCTION,
     {"type": "text", "text": " original text "}),
    ("embed_image", (IMAGE,), IMAGE_QUERY_INSTRUCTION,
     {"type": "image_url", "image_url": {"url": IMAGE}}),
    ("embed_image", (SIGNED,), IMAGE_QUERY_INSTRUCTION,
     {"type": "image_url", "image_url": {"url": SIGNED}}),
    ("embed_media", ("tos://bucket/img.png", SIGNED), IMAGE_CORPUS_INSTRUCTION,
     {"type": "image_url", "image_url": {"url": SIGNED}}),
    ("embed_media", ("tos://bucket/movie.mp4", SIGNED), VIDEO_CORPUS_INSTRUCTION,
     {"type": "video_url", "video_url": {"url": SIGNED}}),
])
async def test_official_embedding_payload(empty_settings, operation, args, instruction, item):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "embedding-1", "model": ARK_EMBEDDING_MODEL,
            "object": "list", "data": {"object": "embedding", "embedding": VECTOR},
            "usage": {"prompt_tokens": 20, "total_tokens": 20},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await getattr(service(http, empty_settings), operation)(*args, api_key="per-user")
    assert result == VECTOR
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/api/v3/embeddings/multimodal"
    assert request.headers["authorization"] == "Bearer per-user"
    assert json.loads(request.content) == {
        "model": ARK_EMBEDDING_MODEL, "dimensions": 1024, "encoding_format": "float",
        "instructions": instruction, "input": [item],
    }


@pytest.mark.parametrize("vector", [
    [], [0.0] * 1024, [1.0] * 1023, [1.0] * 1025, ["1"] * 1024,
    [True] * 1024, [[1]] * 1024, [None] * 1024, [10 ** 1000] * 1024,
])
async def test_bad_vector_rejected_without_padding_or_retry(empty_settings, vector):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "bad-vector", "data": {"embedding": vector}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ServiceError) as captured:
            await service(http, empty_settings).embed_text("test")
    assert len(calls) == 1
    assert captured.value.category == "invalid_vector"
    assert captured.value.request_id == "bad-vector"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
async def test_nonfinite_response_rejected(empty_settings, value):
    body = '{"data":{"embedding":[' + ",".join([value] * 1024) + "]}}"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=body)
    )) as http:
        with pytest.raises(ServiceError):
            await service(http, empty_settings).embed_text("test")


@pytest.mark.parametrize("data", [
    {}, {"data": []}, {"data": [{"embedding": VECTOR}]},
    {"data": {"embedding": None}}, {"data": {"embedding": "float"}},
    {"output": {"embeddings": [{"embedding": VECTOR}]}},
])
async def test_nonofficial_response_shapes_rejected(empty_settings, data):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=data)
    )) as http:
        with pytest.raises(ServiceError) as captured:
            await service(http, empty_settings).embed_text("test")
        assert captured.value.category == "invalid_response"


@pytest.mark.parametrize("kwargs", [
    {"model": "qwen3-vl-embedding"}, {"model": ""}, {"dimension": 768},
    {"dimension": 1024.0}, {"dimension": True}, {"dimension": 0},
])
async def test_space_override_rejected_before_http(empty_settings, kwargs):
    instance = EmbeddingService(config=empty_settings)
    with pytest.raises(VectorSpaceMismatchError):
        await instance.embed_text("test", **kwargs)
    assert instance._client._client is None
    assert not hasattr(instance, "get_model_for_dimension")


async def test_batch_has_one_sample_per_call_and_reports_failures(empty_settings):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 2:
            return httpx.Response(401, json={"error": {"message": "SECRET"}})
        return httpx.Response(200, json={"data": {"embedding": VECTOR}})

    async def sign(url):
        return "https://bucket.invalid/" + url.rsplit("/", 1)[-1]

    urls = ["tos://bucket/one.png", "tos://bucket/two.mp4"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await service(http, empty_settings).batch_embed(urls, sign)
    assert len(calls) == 2
    assert all(len(call["input"]) == 1 for call in calls)
    assert calls[0]["instructions"] == IMAGE_CORPUS_INSTRUCTION
    assert calls[1]["instructions"] == VIDEO_CORPUS_INSTRUCTION
    assert result[urls[0]]["vector"] == VECTOR
    assert result[urls[1]]["status"] == "failed"
    assert result[urls[1]]["vector"] is None
    assert "SECRET" not in result[urls[1]]["error"]


async def test_check_connection_is_explicit_model_probe(empty_settings):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": {"embedding": VECTOR}})
    )) as http:
        result = await service(http, empty_settings).check_connection()
    assert result == {"service": "ark", "status": "ok", "model": ARK_EMBEDDING_MODEL, "dimension": 1024}


def test_user_config_and_frozen_space(empty_settings):
    instance = EmbeddingService.from_settings({"ark_api_key": "user-key"}, config=empty_settings)
    assert instance._client.config.ARK_API_KEY == "user-key"
    assert empty_settings.ARK_API_KEY == ""
    for values in ({"embedding_model": "other"}, {"embedding_dimension": 1024.0}):
        with pytest.raises(VectorSpaceMismatchError):
            EmbeddingService.from_settings(values, config=empty_settings)
