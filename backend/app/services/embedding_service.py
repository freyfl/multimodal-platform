"""Ark single-sample dense embeddings for ingestion and cross-modal search."""

from typing import List, Optional

from app.config import Settings
from app.errors import ServiceError, VectorSpaceMismatchError
from app.services.ark_client import (
    ArkClient, ark_client, invalid_response, media_kind, validate_media_url,
)
from app.vector_space import (
    IMAGE_CORPUS_INSTRUCTION, IMAGE_QUERY_INSTRUCTION,
    TEXT_QUERY_INSTRUCTION, VIDEO_CORPUS_INSTRUCTION,
)


class EmbeddingService:
    """Close at lifespan shutdown; an injected ArkClient shares that lifecycle."""

    def __init__(self, *, client: Optional[ArkClient] = None,
                 config: Optional[Settings] = None):
        self._client = client if client is not None else ArkClient(config=config)
        self.vector_space = self._client.config.vector_space
        self.default_model = self.vector_space.model
        self.default_dimension = self.vector_space.dimension

    @classmethod
    def from_settings(cls, user_settings: dict, *, config: Optional[Settings] = None):
        from app.config import settings

        base = config or settings
        # User overrides cannot select a different vector space.
        if (
            user_settings.get("embedding_model") not in (None, base.ARK_EMBEDDING_MODEL)
            or (
                user_settings.get("embedding_dimension") is not None
                and (
                    type(user_settings["embedding_dimension"]) is not int
                    or user_settings["embedding_dimension"] != base.EMBEDDING_DIMENSION
                )
            )
        ):
            raise VectorSpaceMismatchError()
        return cls(config=base.model_copy(update={
            "ARK_API_KEY": user_settings.get("ark_api_key") or "",
        }))

    def _validate_space(self, model, dimension):
        if (
            (model is not None and model != self.default_model)
            or (dimension is not None and (
                type(dimension) is not int or dimension != self.default_dimension
            ))
        ):
            raise VectorSpaceMismatchError()

    async def _embed(self, item: dict, instruction: str, model, dimension, api_key):
        self._validate_space(model, dimension)
        # Multiple input items fuse into ONE sample, not a batch. Each call here
        # intentionally contains one media/text sample and returns one vector.
        data = await self._client.post("/embeddings/multimodal", {
            "model": self.default_model,
            "dimensions": self.default_dimension,
            "encoding_format": "float",
            "instructions": instruction,
            "input": [item],
        }, api_key=api_key)
        if not isinstance(data.get("data"), dict) or not isinstance(data["data"].get("embedding"), list):
            raise invalid_response(data.get("id"))
        try:
            return self.vector_space.validate_vector(data["data"]["embedding"])
        except ServiceError:
            raise ServiceError(
                "ark", "invalid_vector", request_id=data.get("id"), status_code=502,
            ) from None

    async def embed_media(
        self, tos_url: str, signed_url: Optional[str] = None,
        model: Optional[str] = None, dimension: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> List[float]:
        kind = media_kind(tos_url)
        url = validate_media_url(signed_url if signed_url is not None else tos_url, kind)
        field = f"{kind}_url"
        instruction = VIDEO_CORPUS_INSTRUCTION if kind == "video" else IMAGE_CORPUS_INSTRUCTION
        return await self._embed(
            {"type": field, field: {"url": url}}, instruction, model, dimension, api_key,
        )

    async def embed_text(
        self, text: str, model: Optional[str] = None,
        dimension: Optional[int] = None, api_key: Optional[str] = None,
    ) -> List[float]:
        if not isinstance(text, str) or not text.strip():
            raise ServiceError("ark", "invalid_request", status_code=400)
        return await self._embed(
            {"type": "text", "text": text}, TEXT_QUERY_INSTRUCTION, model, dimension, api_key,
        )

    async def embed_image(
        self, image_url: str, model: Optional[str] = None,
        dimension: Optional[int] = None, api_key: Optional[str] = None,
    ) -> List[float]:
        """Query-side image URL or data:image/<mime>;base64,..., never Corpus.

        Official embedding docs explicitly support Base64 images (<10 MiB);
        no temporary TOS object is required and uploaded-image search is kept.
        """
        url = validate_media_url(image_url, "image")
        return await self._embed(
            {"type": "image_url", "image_url": {"url": url}},
            IMAGE_QUERY_INSTRUCTION, model, dimension, api_key,
        )

    async def batch_embed(self, media_urls: List[str], get_signed_url_func=None,
                          api_key: Optional[str] = None) -> dict:
        results = {}
        for url in media_urls:
            try:
                signed = await get_signed_url_func(url) if get_signed_url_func else None
                vector = await self.embed_media(url, signed, api_key=api_key)
                results[url] = {"vector": vector, "status": "success"}
            except Exception as exc:
                error = exc if isinstance(exc, ServiceError) else ServiceError("ark", "unavailable")
                results[url] = {"vector": None, "status": "failed", "error": str(error)}
        return results

    async def check_connection(self, api_key: Optional[str] = None) -> dict:
        """Explicit, billable model probe; never call this from normal health checks."""
        vector = await self.embed_text("road scene", api_key=api_key)
        return {
            "service": "ark", "status": "ok", "model": self.default_model,
            "dimension": len(vector),
        }

    async def aclose(self) -> None:
        await self._client.aclose()


# Both global services share a budget and close the same client idempotently.
embedding_service = EmbeddingService(client=ark_client)
