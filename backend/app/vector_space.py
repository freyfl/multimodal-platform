"""Versioned vector-space identity shared by ingestion, queries and storage."""

import math
from dataclasses import asdict, dataclass
from numbers import Real
from typing import List, Mapping, Sequence

from app.errors import ServiceError, VectorSpaceMismatchError


ARK_TAG_MODEL = "doubao-seed-2-1-lite-260915"
ARK_EMBEDDING_MODEL = "doubao-embedding-vision-251215"
EMBEDDING_DIMENSION = 1024
EMBEDDING_CORPUS_INSTRUCTION_VERSION = "road-scene-corpus-v1"
EMBEDDING_QUERY_INSTRUCTION_VERSION = "road-scene-query-v1"

IMAGE_CORPUS_INSTRUCTION = "Instruction:Compress the image into one word.\nQuery:"
VIDEO_CORPUS_INSTRUCTION = "Instruction:Compress the video into one word.\nQuery:"
TEXT_QUERY_INSTRUCTION = (
    "Target_modality: image/video.\n"
    "Instruction:\u6839\u636e\u63cf\u8ff0\u68c0\u7d22\u5339\u914d\u7684"
    "\u81ea\u52a8\u9a7e\u9a76\u9053\u8def\u573a\u666f\u56fe\u7247\u6216\u89c6\u9891\nQuery:"
)
IMAGE_QUERY_INSTRUCTION = (
    "Target_modality: image/video.\n"
    "Instruction:\u68c0\u7d22\u4e0e\u8f93\u5165\u56fe\u7247\u89c6\u89c9\u5185\u5bb9"
    "\u548c\u9053\u8def\u573a\u666f\u76f8\u4f3c\u7684\u56fe\u7247\u6216\u89c6\u9891\nQuery:"
)

EMBEDDING_MODELS = {
    ARK_EMBEDDING_MODEL: {
        "name": ARK_EMBEDDING_MODEL,
        "dimensions": [EMBEDDING_DIMENSION],
        "default_dimension": EMBEDDING_DIMENSION,
    }
}
TAG_MODELS = {
    ARK_TAG_MODEL: {"name": ARK_TAG_MODEL, "description": "Volcengine Ark Seed 2.1 Lite"}
}


@dataclass(frozen=True)
class VectorSpace:
    model: str = ARK_EMBEDDING_MODEL
    dimension: int = EMBEDDING_DIMENSION
    corpus_instruction_version: str = EMBEDDING_CORPUS_INSTRUCTION_VERSION
    query_instruction_version: str = EMBEDDING_QUERY_INSTRUCTION_VERSION
    collection: str = "media_vectors_v1"

    def __post_init__(self):
        if (
            self.model != ARK_EMBEDDING_MODEL
            or type(self.dimension) is not int
            or self.dimension != EMBEDDING_DIMENSION
            or self.corpus_instruction_version != EMBEDDING_CORPUS_INSTRUCTION_VERSION
            or self.query_instruction_version != EMBEDDING_QUERY_INSTRUCTION_VERSION
            or not self.collection
        ):
            raise VectorSpaceMismatchError()

    def to_dict(self) -> dict:
        return asdict(self)

    def assert_compatible(self, actual: Mapping) -> None:
        """Missing identity fields also require an explicit rebuild."""
        expected = self.to_dict()
        if any(actual.get(key) != value for key, value in expected.items()):
            raise VectorSpaceMismatchError()
        if type(actual.get("dimension")) is not int:
            raise VectorSpaceMismatchError()

    def validate_vector(self, vector: Sequence[float]) -> List[float]:
        return validate_vector(vector, self.dimension)


def validate_vector(vector: Sequence[float], dimension: int = EMBEDDING_DIMENSION) -> List[float]:
    """Reject malformed vectors; never pad, truncate or infer their model."""
    try:
        if isinstance(vector, (str, bytes)) or len(vector) != dimension:
            raise ValueError
        result = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError
            value = float(value)
            if not math.isfinite(value):
                raise ValueError
            result.append(value)
        if not result or not any(value != 0 for value in result):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ServiceError("ark", "invalid_vector", status_code=422) from None
    return result


def cosine_to_similarity(cosine: float) -> float:
    if isinstance(cosine, bool) or not isinstance(cosine, Real) or not math.isfinite(cosine):
        raise ServiceError("milvus", "invalid_response", status_code=502)
    return max(0.0, min(1.0, float(cosine)))
