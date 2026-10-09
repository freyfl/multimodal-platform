"""Frame-level annotation through the application's shared Ark transport."""

import base64
from io import BytesIO
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError

from app.errors import MissingConfigurationError, ServiceError
from app.models.annotation_schemas import (
    ANNOTATION_MODEL, AnnotationModelResponse, AnnotationRuleSnapshot,
)
from app.services.annotation_frame_service import (
    AnnotationFrameService, FrameStorageContext, PreparedFrame,
)
from app.services.annotation_rules import (
    ANNOTATION_OUTPUT_CONTRACT, parse_annotation_response,
)
from app.services.ark_client import (
    ArkClient, ark_client, response_text, validate_media_url,
)


class AnnotationService:
    """Borrow ArkClient; its lifespan owner, not this adapter, closes it."""

    def __init__(self, *, client: ArkClient | None = None, model_long_edge=2048):
        if type(model_long_edge) is not int or not 1 <= model_long_edge <= 4096:
            raise ValueError("Invalid model image limit")
        self._client = client if client is not None else ark_client
        self.model_long_edge = model_long_edge

    @staticmethod
    def _api_key(api_key):
        if not isinstance(api_key, str) or not api_key.strip():
            raise MissingConfigurationError("ark", ["ARK_API_KEY"])
        return api_key

    def _image_data_url(self, frame: PreparedFrame, context: FrameStorageContext):
        path = AnnotationFrameService.resolve_frame_path(context, frame.storage_key)
        # Do not trust a caller-supplied absolute path, even on a reconstructed DTO.
        try:
            if path.stat().st_size > 128 * 1024**2:
                raise ValueError
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.size != (frame.width, frame.height) or image.width * image.height > 7680 * 4320:
                        raise ValueError
                    image.thumbnail(
                        (self.model_long_edge, self.model_long_edge), Image.Resampling.LANCZOS,
                    )
                    with image.convert("RGB") as rgb:
                        output = BytesIO()
                        rgb.save(output, format="JPEG", quality=90)
            data = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
            return validate_media_url(data, "image")
        except (Image.DecompressionBombError, Image.DecompressionBombWarning,
                UnidentifiedImageError, OSError, ValueError):
            raise ServiceError("application", "invalid_request", status_code=422) from None

    async def generate_annotations(
        self, image_url: str, *, snapshot: AnnotationRuleSnapshot, api_key: str,
    ) -> AnnotationModelResponse:
        """Internal data-URI input only. No media download or credential fallback."""
        key = self._api_key(api_key)
        snapshot = AnnotationRuleSnapshot.model_validate(snapshot.model_dump())
        if not isinstance(image_url, str) or not image_url.startswith("data:image/"):
            raise ServiceError("ark", "invalid_request", status_code=422)
        image_url = validate_media_url(image_url, "image")
        data = await self._client.post("/responses", {
            "model": snapshot.model,
            "stream": False,
            "input": [
                {"role": "system", "content": [{
                    "type": "input_text",
                    "text": ANNOTATION_OUTPUT_CONTRACT
                    + f"\nRequired box mode: {snapshot.annotation_box_mode}.",
                }]},
                {"role": "user", "content": [
                    {"type": "input_image", "image_url": image_url},
                    {"type": "input_text", "text": snapshot.prompt},
                ]},
            ],
        }, api_key=key)
        try:
            return parse_annotation_response(
                response_text(data), annotation_mode=snapshot.annotation_mode,
                annotation_box_mode=snapshot.annotation_box_mode,
            )
        except ServiceError:
            raise ServiceError(
                "ark", "invalid_response", request_id=data.get("id"),
                retryable=True, status_code=502,
            ) from None

    async def annotate_frame(
        self, frame: PreparedFrame, user_config: dict, *,
        snapshot: AnnotationRuleSnapshot, context: FrameStorageContext,
    ) -> list[dict]:
        """Validate a complete frame, then assign independent server object IDs.

        T4 owns persistence and retry decisions. Exceptions must remain failures;
        only a successfully parsed empty objects array means no visible targets.
        """
        key = self._api_key(user_config.get("ark_api_key"))
        model = user_config.get("tag_model")
        if not isinstance(model, str) or not model.strip():
            raise MissingConfigurationError("ark", ["ARK_TAG_MODEL"])
        if model != ANNOTATION_MODEL or model != snapshot.model:
            raise ServiceError("ark", "invalid_request", status_code=422)
        image_url = self._image_data_url(frame, context)
        response = await self.generate_annotations(image_url, snapshot=snapshot, api_key=key)
        return [dict(obj.model_dump(), object_id=str(uuid4())) for obj in response.objects]


annotation_service = AnnotationService()
