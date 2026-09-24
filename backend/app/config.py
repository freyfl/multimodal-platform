"""Validated public configuration; no clients or network activity on import."""

import os
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.errors import MissingConfigurationError
from app.vector_space import (
    ARK_EMBEDDING_MODEL, ARK_TAG_MODEL, EMBEDDING_DIMENSION,
    EMBEDDING_CORPUS_INSTRUCTION_VERSION, EMBEDDING_QUERY_INSTRUCTION_VERSION,
    EMBEDDING_MODELS, TAG_MODELS, VectorSpace,
)


class Settings(BaseSettings):
    """Empty credentials allow discovery; services call require_config on use."""

    model_config = SettingsConfigDict(
        env_file=None, env_file_encoding="utf-8", case_sensitive=True,
        extra="ignore", hide_input_in_errors=True,
    )

    APP_NAME: str = "多模态数据检索平台"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api"

    TOS_ACCESS_KEY_ID: str = Field(default="", repr=False, exclude=True)
    TOS_ACCESS_KEY_SECRET: str = Field(default="", repr=False, exclude=True)
    TOS_SECURITY_TOKEN: str = Field(default="", repr=False, exclude=True)
    TOS_BUCKET_NAME: str = ""
    TOS_ENDPOINT: str = ""
    TOS_REGION: str = "cn-beijing"
    TOS_CUSTOM_DOMAIN: str = ""
    TOS_SIGNED_URL_EXPIRES: int = Field(default=3600, ge=60, le=604800)

    ARK_API_KEY: str = Field(default="", repr=False, exclude=True)
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    ARK_TAG_MODEL: Literal["doubao-seed-2-1-lite-260915"] = ARK_TAG_MODEL
    ARK_EMBEDDING_MODEL: Literal["doubao-embedding-vision-251215"] = ARK_EMBEDDING_MODEL
    ARK_REQUEST_TIMEOUT: float = Field(default=300, gt=0)
    ARK_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    ARK_RETRY_BASE_DELAY: float = Field(default=1, gt=0)
    ARK_RETRY_MAX_DELAY: float = Field(default=30, gt=0)
    ARK_MAX_CONCURRENCY: int = Field(default=5, ge=1)

    EMBEDDING_DIMENSION: Literal[1024] = EMBEDDING_DIMENSION
    EMBEDDING_CORPUS_INSTRUCTION_VERSION: Literal["road-scene-corpus-v1"] = EMBEDDING_CORPUS_INSTRUCTION_VERSION
    EMBEDDING_QUERY_INSTRUCTION_VERSION: Literal["road-scene-query-v1"] = EMBEDDING_QUERY_INSTRUCTION_VERSION
    TEXT_SEARCH_MIN_SCORE: float = Field(default=0, ge=0, le=1)

    MILVUS_URI: str = ""
    MILVUS_DB_NAME: str = "default"
    MILVUS_TOKEN: str = Field(default="", repr=False, exclude=True)
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = Field(default="", repr=False, exclude=True)
    MILVUS_AUTH_ENABLED: bool = False
    MILVUS_SECURE: bool = True
    MILVUS_CA_CERT: str = ""
    MILVUS_SERVER_NAME: str = ""
    MILVUS_TIMEOUT: float = Field(default=30, gt=0)
    MILVUS_COLLECTION: str = Field(default="media_vectors_v2", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
    MILVUS_METRIC_TYPE: Literal["COSINE"] = "COSINE"
    MILVUS_INDEX_TYPE: Literal["HNSW"] = "HNSW"
    MILVUS_HNSW_M: int = Field(default=16, ge=2, le=2048)
    MILVUS_HNSW_EF_CONSTRUCTION: int = Field(default=200, ge=1)
    MILVUS_SEARCH_EF: int = Field(default=100, ge=1)
    MILVUS_CONSISTENCY_LEVEL: Literal["Strong"] = "Strong"

    MYSQL_HOST: str = ""
    MYSQL_PORT: int = Field(default=3306, ge=1, le=65535)
    MYSQL_DATABASE: str = "multimodal_platform"
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = Field(default="", repr=False, exclude=True)
    MYSQL_SSL_ENABLED: bool = True
    MYSQL_SSL_CA: str = ""
    MYSQL_CONNECT_TIMEOUT: int = Field(default=10, ge=1)

    JWT_SECRET_KEY: str = Field(default="", repr=False, exclude=True)
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=1)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, ge=1)
    ALLOW_REGISTRATION: bool = True
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = Field(default="", repr=False, exclude=True)
    MAX_CONCURRENT_TASKS: int = Field(default=5, ge=1)
    TASK_TIMEOUT: int = Field(default=7200, ge=1)
    CLOUD_IO_MAX_WORKERS: int = Field(default=5, ge=1)
    ANNOTATION_STORAGE_DIR: str = ""
    ANNOTATION_TEMP_DIR: str = ""
    ANNOTATION_DECODE_TIMEOUT: float = Field(default=300, gt=0)
    ANNOTATION_MAX_VIDEO_BYTES: int = Field(default=2 * 1024**3, ge=1)
    ANNOTATION_MAX_VIDEO_SECONDS: int = Field(default=1800, ge=1)
    ANNOTATION_MAX_FRAME_PIXELS: int = Field(default=7680 * 4320, ge=1)
    ANNOTATION_MAX_FRAME_LONG_EDGE: int = Field(default=7680, ge=1)
    ANNOTATION_MAX_FRAME_SHORT_EDGE: int = Field(default=4320, ge=1)
    ANNOTATION_DECODE_CONCURRENCY: Literal[1] = 1

    @field_validator("EMBEDDING_DIMENSION", mode="before")
    @classmethod
    def parse_embedding_dimension(cls, value):
        # Environment values are strings; only the chosen dimension is accepted.
        return 1024 if value == "1024" else value

    @field_validator("ANNOTATION_DECODE_CONCURRENCY", mode="before")
    @classmethod
    def parse_annotation_decode_concurrency(cls, value):
        return 1 if value == "1" else value

    def require_config(self, service: str) -> None:
        required = {
            "tos": ("TOS_ACCESS_KEY_ID", "TOS_ACCESS_KEY_SECRET", "TOS_BUCKET_NAME", "TOS_ENDPOINT", "TOS_REGION"),
            "ark": ("ARK_API_KEY", "ARK_BASE_URL"),
            "milvus": ("MILVUS_URI", "MILVUS_DB_NAME", "MILVUS_COLLECTION"),
            "mysql": ("MYSQL_HOST", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"),
            "application": ("JWT_SECRET_KEY",),
        }
        if service not in required:
            raise ValueError("Unknown service configuration")
        missing = [key for key in required[service] if not getattr(self, key).strip()]
        if service == "milvus" and self.MILVUS_AUTH_ENABLED and not self.MILVUS_TOKEN.strip():
            missing.extend(key for key in ("MILVUS_USER", "MILVUS_PASSWORD") if not getattr(self, key).strip())
        if missing:
            raise MissingConfigurationError(service, missing)

    @property
    def vector_space(self) -> VectorSpace:
        return VectorSpace(
            model=self.ARK_EMBEDDING_MODEL, dimension=self.EMBEDDING_DIMENSION,
            corpus_instruction_version=self.EMBEDDING_CORPUS_INSTRUCTION_VERSION,
            query_instruction_version=self.EMBEDDING_QUERY_INSTRUCTION_VERSION,
            collection=self.MILVUS_COLLECTION,
        )

    def _mysql_url(self, driver: str) -> URL:
        return URL.create(
            driver, username=self.MYSQL_USER, password=self.MYSQL_PASSWORD,
            host=self.MYSQL_HOST, port=self.MYSQL_PORT, database=self.MYSQL_DATABASE,
            query={"charset": "utf8mb4"},
        )

    @property
    def mysql_url(self) -> URL:
        return self._mysql_url("mysql+aiomysql")

    @property
    def mysql_sync_url(self) -> URL:
        return self._mysql_url("mysql+pymysql")


def get_model_catalog(config: Settings = None) -> dict:
    """Shape of /system/config's data.model_catalog; contains no credentials."""
    config = config or settings
    return {
        "embedding_models": {key: {**value, "dimensions": list(value["dimensions"])} for key, value in EMBEDDING_MODELS.items()},
        "tag_models": {key: dict(value) for key, value in TAG_MODELS.items()},
        "defaults": {
            "embedding_model": config.ARK_EMBEDDING_MODEL,
            "embedding_dimension": config.EMBEDDING_DIMENSION,
            "tag_model": config.ARK_TAG_MODEL,
            "text_search_min_score": config.TEXT_SEARCH_MIN_SCORE,
        },
        "vector_space": config.vector_space.to_dict(),
    }


# Dotenv is opt-in so importing contracts never reads a developer's local secrets.
# Deployment can export variables or explicitly set APP_ENV_FILE=/path/to/.env.
settings = Settings(_env_file=os.environ.get("APP_ENV_FILE") or None)
