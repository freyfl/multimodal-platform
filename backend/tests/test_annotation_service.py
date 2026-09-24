import asyncio
import base64
from dataclasses import replace
from io import BytesIO
import json
from uuid import UUID, uuid4

import httpx
from PIL import Image
import pytest

from app.errors import ServiceError
from app.models.annotation_schemas import ANNOTATION_MODEL, AnnotationOptions
from app.services.annotation_frame_service import FrameStorageContext, PreparedFrame
from app.services.annotation_rules import ANNOTATION_OUTPUT_CONTRACT, build_rule_snapshot
from app.services.annotation_service import AnnotationService
from app.services.ark_client import ArkClient, ark_client
from app.services.tag_service import TagService


@pytest.fixture
def snapshot():
    return build_rule_snapshot(
        AnnotationOptions(), model=ANNOTATION_MODEL, source_etag='"v1"', source_version="1",
    )


@pytest.fixture
def prepared(tmp_path):
    context = FrameStorageContext("owner", "media", "revision", tmp_path / "frames", tmp_path / "temp")
    identity = uuid4().hex
    key = f"owner/media/revision/{identity}.png"
    path = context.storage_dir / key
    path.parent.mkdir(parents=True)
    with Image.new("RGB", (2400, 1200), "blue") as image:
        image.save(path)
    return PreparedFrame(identity, 0, None, 2400, 1200, key, path), context


@pytest.fixture
def user_config():
    return {"ark_api_key": "owner-key", "tag_model": ANNOTATION_MODEL}


@pytest.fixture
def object_value():
    return {
        "category": "vehicle", "name": "car", "confidence": 0.8,
        "bbox_2d": [0.1, 0.2, 0.5, 0.8], "cuboid_3d": None,
        "cuboid_unavailable_reason": "occluded", "occluded": True, "truncated": False,
    }


def envelope(text):
    return {
        "id": "response-1", "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text}]}],
    }


async def test_data_url_snapshot_owner_key_exact_frame_and_independent_ids(
    empty_settings, snapshot, prepared, user_config, object_value,
):
    seen = []
    other = {**object_value, "bbox_2d": [0.6, 0.2, 0.9, 0.8]}

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=envelope(json.dumps({"objects": [object_value, object_value, other]})))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        config = empty_settings.model_copy(update={"ARK_API_KEY": "deployment-key"})
        service = AnnotationService(client=ArkClient(config=config, http_client=http))
        frame, context = prepared
        objects = await service.annotate_frame(frame, user_config, snapshot=snapshot, context=context)
    assert len(objects) == 2
    assert objects[0]["object_id"] != objects[1]["object_id"]
    assert all(UUID(obj["object_id"]).version == 4 for obj in objects)
    assert seen[0].headers["Authorization"] == "Bearer owner-key"
    assert seen[0].url.path == "/api/v3/responses"
    payload = json.loads(seen[0].content)
    assert payload["model"] == ANNOTATION_MODEL
    assert payload["input"][0]["content"][0]["text"].startswith(ANNOTATION_OUTPUT_CONTRACT)
    assert payload["input"][1]["content"][1]["text"] == snapshot.prompt
    image_url = payload["input"][1]["content"][0]["image_url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    with Image.open(BytesIO(base64.b64decode(image_url.split(",")[1]))) as image:
        assert image.size == (2048, 1024)
    with Image.open(frame.path) as image:
        assert image.size == (2400, 1200)


@pytest.mark.parametrize("changes", [
    {"ark_api_key": None}, {"ark_api_key": ""}, {"ark_api_key": " "},
    {"tag_model": None}, {"tag_model": ""}, {"tag_model": "another-model"},
])
async def test_user_credentials_never_fall_back(empty_settings, snapshot, prepared, user_config, changes):
    config = empty_settings.model_copy(update={"ARK_API_KEY": "deployment-key"})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope('{"objects":[]}'))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = AnnotationService(client=ArkClient(config=config, http_client=http))
        with pytest.raises(ServiceError):
            await service.annotate_frame(
                prepared[0], {**user_config, **changes}, snapshot=snapshot, context=prepared[1],
            )
    assert not calls


@pytest.mark.parametrize("kind", ["empty", "truncated", "duplicate_key", "invalid_box", "model_id", "incomplete", "excessive", "invalid_cuboid"])
async def test_invalid_response_is_not_empty_success(
    empty_settings, snapshot, prepared, user_config, object_value, kind,
):
    text = '{"objects":[]}'
    if kind == "truncated":
        text = '{"objects":['
    elif kind == "duplicate_key":
        text = '{"objects":[],"objects":[]}'
    elif kind == "invalid_box":
        text = json.dumps({"objects": [{**object_value, "bbox_2d": [0, 0, 2, 1]}]})
    elif kind == "model_id":
        text = json.dumps({"objects": [{**object_value, "object_id": "model-invented"}]})
    elif kind == "excessive":
        text = json.dumps({"objects": [object_value] * 201})
    elif kind == "invalid_cuboid":
        text = json.dumps({"objects": [{**object_value, "cuboid_3d": [[0, 0]] * 8, "cuboid_unavailable_reason": None}]})
    response = envelope(text)
    if kind == "incomplete":
        response["status"] = "incomplete"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))) as http:
        service = AnnotationService(client=ArkClient(config=empty_settings, http_client=http))
        if kind == "empty":
            assert await service.annotate_frame(prepared[0], user_config, snapshot=snapshot, context=prepared[1]) == []
        else:
            with pytest.raises(ServiceError) as error:
                await service.annotate_frame(prepared[0], user_config, snapshot=snapshot, context=prepared[1])
            assert error.value.category == "invalid_response"
            assert error.value.request_id == "response-1" and error.value.retryable


async def test_default_transport_is_the_shared_instance():
    assert AnnotationService()._client is ark_client


async def test_annotation_and_tag_share_ark_concurrency(empty_settings, snapshot, prepared, user_config):
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        payload = json.loads(request.content)
        text = '{"objects":[]}' if payload["input"][0]["role"] == "system" else '{"tags":[]}'
        return httpx.Response(200, json=envelope(text))

    config = empty_settings.model_copy(update={"ARK_MAX_CONCURRENCY": 1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ArkClient(config=config, http_client=http)
        service = AnnotationService(client=client)
        frame, context = prepared
        image_url = service._image_data_url(frame, context)
        await asyncio.gather(
            service.annotate_frame(frame, user_config, snapshot=snapshot, context=context),
            TagService(client=client).generate_tags("tos://bucket/a.jpg", image_url, api_key="owner-key"),
        )
        assert peak == 1
        assert not http.is_closed


async def test_absolute_dto_path_is_ignored_and_owner_key_is_checked(prepared):
    frame, context = prepared
    service = AnnotationService()
    data = service._image_data_url(replace(frame, path=context.temp_dir / "untrusted"), context)
    assert data.startswith("data:image/jpeg;base64,")
    with pytest.raises(ServiceError):
        service._image_data_url(frame, replace(context, user_id="other"))
    with pytest.raises(ServiceError):
        service._image_data_url(replace(frame, width=1), context)


@pytest.mark.parametrize("url", ["https://example.invalid/a.png", "file:///etc/passwd", "tos://bucket/a.png"])
async def test_generation_does_not_accept_remote_urls(snapshot, url):
    with pytest.raises(ServiceError):
        await AnnotationService().generate_annotations(url, snapshot=snapshot, api_key="owner-key")
