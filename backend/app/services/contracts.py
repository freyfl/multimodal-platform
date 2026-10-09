"""Shared service signatures. Constructors are lazy and accept injected clients.

All I/O methods are async. TOS and Milvus implementations run synchronous SDK
calls in a bounded executor. App lifespan owns instances and awaits aclose().
from_settings receives the effective user settings dict (lowercase TOS/Ark
fields), never a database session. Exceptions use app.errors.ServiceError.
"""

from typing import AsyncIterator, Dict, List, Literal, Optional, Protocol, Sequence, TypedDict


class MediaObject(TypedDict):
    tos_url: str
    file_name: str
    file_type: str
    file_size: int


class VectorRecord(TypedDict):
    user_id: str
    media_id: str
    tos_url: str
    file_type: str
    embedding: List[float]


class VectorHit(TypedDict):
    user_id: str
    media_id: str
    tos_url: str
    file_type: str
    score: float


class ObjectStream(Protocol):
    """Proxy returns upstream status/headers unchanged and always closes stream."""
    status_code: int
    headers: Dict[str, str]

    def aiter_bytes(self) -> AsyncIterator[bytes]: ...
    async def aclose(self) -> None: ...


class TOSContract(Protocol):
    @classmethod
    def from_settings(cls, user_settings: dict) -> "TOSContract": ...
    async def list_files(self, directory: str) -> List[MediaObject]: ...
    async def file_exists(self, tos_url: str) -> bool: ...
    async def get_file_url(self, tos_url: str, expires: int = 3600) -> str: ...
    async def get_preview_url(self, tos_url: str, expires: int = 3600) -> str: ...
    async def download_file(self, tos_url: str, local_path: str) -> bool: ...
    async def upload_file(self, local_path: str, tos_path: str) -> bool: ...
    async def delete_file(self, tos_url: str) -> None: ...
    async def open_object(
        self, tos_url: str, *, method: str = "GET", range_header: Optional[str] = None
    ) -> ObjectStream: ...
    async def check_connection(self) -> dict: ...
    async def aclose(self) -> None: ...


class EmbeddingContract(Protocol):
    async def embed_media(
        self, tos_url: str, signed_url: Optional[str] = None,
        model: Optional[str] = None, dimension: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> List[float]: ...
    async def embed_text(
        self, text: str, model: Optional[str] = None,
        dimension: Optional[int] = None, api_key: Optional[str] = None,
    ) -> List[float]: ...
    async def embed_image(
        self, image_url: str, model: Optional[str] = None,
        dimension: Optional[int] = None, api_key: Optional[str] = None,
    ) -> List[float]: ...
    async def check_connection(self, api_key: Optional[str] = None) -> dict: ...
    async def aclose(self) -> None: ...


class TagContract(Protocol):
    async def generate_tags(
        self, tos_url: str, signed_url: Optional[str] = None,
        model: Optional[str] = None, api_key: Optional[str] = None,
        tag_mode: Literal["default", "custom"] = "default",
        custom_prompt: Optional[str] = None,
    ) -> List[dict]: ...
    def get_tag_system(self) -> Dict[str, List[str]]: ...
    async def check_connection(self, api_key: Optional[str] = None) -> dict: ...
    async def aclose(self) -> None: ...


class MilvusContract(Protocol):
    """Mutations raise on failure. Reads are strong-consistent; count is exact.

    Collection config is VectorSpace.to_dict(). ensure_collection may create a
    missing collection but must reject incompatible metadata without dropping it.
    Hits use score=clamp(cosine, 0, 1), descending, min_score applied afterwards.
    """
    async def ensure_collection(self) -> None: ...
    async def get_collection_config(self) -> dict: ...
    async def upsert(
        self, user_id: str, media_id: str, tos_url: str,
        file_type: str, embedding: Sequence[float],
    ) -> str: ...
    async def batch_upsert(self, records: Sequence[VectorRecord]) -> List[str]: ...
    async def search(
        self, query_vector: Sequence[float], top_k: int = 20,
        min_score: float = 0.0, user_id: Optional[str] = None,
    ) -> List[VectorHit]: ...
    async def delete(self, media_id: str) -> None: ...
    async def get_vector_count(self, user_id: Optional[str] = None) -> int: ...
    async def check_connection(self) -> dict: ...
    async def aclose(self) -> None: ...
