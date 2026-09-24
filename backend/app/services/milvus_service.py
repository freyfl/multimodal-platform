"""Lazy, strong-consistent Milvus storage for the frozen vector-space contract."""

import asyncio
import json
import math
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from numbers import Real
from typing import List, Optional

import grpc
from pymilvus import DataType, MilvusClient
from pymilvus.exceptions import ErrorCode, ParamError

from app.config import Settings, settings
from app.errors import ServiceError, VectorSpaceMismatchError
from app.services.contracts import VectorHit, VectorRecord
from app.vector_space import cosine_to_similarity


class MilvusService:
    """One instance per application lifespan; await aclose() before shutdown.

    Collection description is JSON containing exactly VectorSpace.to_dict().
    No legacy metadata inference, estimated counts or automatic drops are used.
    Caller retries of failed upserts must use the same media ID.
    """

    INDEX_NAME = "embedding_hnsw"
    STRING_LENGTHS = {
        "media_id": 256, "user_id": 64, "tos_url": 8192, "file_type": 16,
    }
    MAX_TOP_K = 16384

    def __init__(self, config: Optional[Settings] = None, *, client=None):
        self._config = (config or settings).model_copy(deep=True)
        self._space = self._config.vector_space
        self._client = client
        self._executor = None
        self._slots = asyncio.Semaphore(self._config.CLOUD_IO_MAX_WORKERS)
        self._pending = set()
        self._init_lock = threading.Lock()
        self._ready = False
        self._closing = False
        self._close_task = None

    @staticmethod
    def _safe_call(func):
        try:
            return func()
        except ServiceError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            if callable(code):
                code = code()
            category, status, retryable = "unavailable", 503, True
            if isinstance(error, TimeoutError) or code == grpc.StatusCode.DEADLINE_EXCEEDED:
                category, status = "timeout", 504
            elif code == grpc.StatusCode.UNAUTHENTICATED:
                category, status, retryable = "authentication", 401, False
            elif code in (grpc.StatusCode.PERMISSION_DENIED, ErrorCode.FORCE_DENY):
                category, status, retryable = "permission", 403, False
            elif code in (grpc.StatusCode.RESOURCE_EXHAUSTED, ErrorCode.RATE_LIMIT):
                category, status = "rate_limit", 429
            elif code in (grpc.StatusCode.NOT_FOUND, ErrorCode.COLLECTION_NOT_FOUND):
                category, status, retryable = "not_found", 404, False
            elif isinstance(error, ParamError) or code == grpc.StatusCode.INVALID_ARGUMENT:
                category, status, retryable = "invalid_request", 422, False
            raise ServiceError(
                "milvus", category, status_code=status, retryable=retryable,
                request_id=getattr(error, "request_id", None),
            ) from None

    async def _run(self, func):
        if self._closing:
            raise ServiceError("milvus", "unavailable")
        await self._slots.acquire()
        try:
            if self._closing:
                raise ServiceError("milvus", "unavailable")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._config.CLOUD_IO_MAX_WORKERS,
                    thread_name_prefix="milvus",
                )
            future = asyncio.get_running_loop().run_in_executor(
                self._executor, self._safe_call, func,
            )
        except BaseException:
            self._slots.release()
            raise
        self._pending.add(future)

        def finished(done):
            self._pending.discard(done)
            self._slots.release()
            # A cancelled coroutine still owns an in-flight synchronous call.
            if not done.cancelled():
                done.exception()

        future.add_done_callback(finished)
        return await asyncio.shield(future)

    def _connect(self):
        if self._client is None:
            self._config.require_config("milvus")
            options = {
                "uri": self._config.MILVUS_URI,
                "db_name": self._config.MILVUS_DB_NAME,
                "timeout": self._config.MILVUS_TIMEOUT,
                "secure": self._config.MILVUS_SECURE,
            }
            if self._config.MILVUS_AUTH_ENABLED:
                if self._config.MILVUS_TOKEN:
                    options["token"] = self._config.MILVUS_TOKEN
                else:
                    options.update(
                        user=self._config.MILVUS_USER,
                        password=self._config.MILVUS_PASSWORD,
                    )
            if self._config.MILVUS_CA_CERT:
                options["ca_pem_path"] = self._config.MILVUS_CA_CERT
            if self._config.MILVUS_SERVER_NAME:
                options["server_name"] = self._config.MILVUS_SERVER_NAME
            self._client = MilvusClient(**options)

    def _call(self, method, **kwargs):
        return getattr(self._client, method)(
            collection_name=self._space.collection,
            timeout=self._config.MILVUS_TIMEOUT,
            **kwargs,
        )

    def _create_collection(self):
        schema = MilvusClient.create_schema(
            auto_id=False, enable_dynamic_field=False,
            description=json.dumps(self._space.to_dict(), sort_keys=True),
        )
        for name, length in self.STRING_LENGTHS.items():
            schema.add_field(
                field_name=name, datatype=DataType.VARCHAR,
                max_length=length, is_primary=name == "media_id",
            )
        schema.add_field(
            field_name="embedding", datatype=DataType.FLOAT_VECTOR,
            dim=self._space.dimension,
        )
        # Create without indexes so all paths validate identity before loading.
        self._call(
            "create_collection", schema=schema,
            consistency_level=self._config.MILVUS_CONSISTENCY_LEVEL,
        )

    def _read_config(self):
        description = self._call("describe_collection")
        try:
            if not isinstance(description, Mapping):
                raise ValueError
            metadata = json.loads(description["description"])
            if not isinstance(metadata, dict):
                raise ValueError
            if set(metadata) != set(self._space.to_dict()):
                raise ValueError
            self._space.assert_compatible(metadata)
            fields = {field["name"]: field for field in description["fields"]}
            if (
                description["collection_name"] != self._space.collection
                or description.get("auto_id", False)
                or description.get("enable_dynamic_field", False)
                or description.get("consistency_level") not in (0, "Strong")
                or set(fields) != {*self.STRING_LENGTHS, "embedding"}
            ):
                raise ValueError
            for name, length in self.STRING_LENGTHS.items():
                field = fields[name]
                if (
                    field["type"] != DataType.VARCHAR
                    or field.get("is_primary", False) != (name == "media_id")
                    or field.get("auto_id", False)
                    or field.get("nullable", False)
                    or self._integer_parameter(field["params"]["max_length"]) < length
                ):
                    raise ValueError
            vector_field = fields["embedding"]
            if (
                vector_field["type"] != DataType.FLOAT_VECTOR
                or self._integer_parameter(vector_field["params"]["dim"]) != self._space.dimension
                or vector_field.get("is_primary", False)
                or vector_field.get("nullable", False)
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            raise VectorSpaceMismatchError() from None
        return {key: metadata[key] for key in self._space.to_dict()}

    @staticmethod
    def _integer_parameter(value):
        if type(value) is int:
            return value
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        raise ValueError

    def _ensure_index(self):
        indexes = self._call("list_indexes", field_name="embedding")
        if not isinstance(indexes, list):
            raise ServiceError("milvus", "invalid_response", status_code=502)
        if not indexes:
            params = MilvusClient.prepare_index_params()
            params.add_index(
                field_name="embedding", index_name=self.INDEX_NAME,
                index_type=self._config.MILVUS_INDEX_TYPE,
                metric_type=self._config.MILVUS_METRIC_TYPE,
                params={
                    "M": self._config.MILVUS_HNSW_M,
                    "efConstruction": self._config.MILVUS_HNSW_EF_CONSTRUCTION,
                },
            )
            self._call("create_index", index_params=params)
            indexes = [self.INDEX_NAME]
        if len(indexes) != 1:
            raise VectorSpaceMismatchError()
        index = self._call("describe_index", index_name=indexes[0])
        try:
            if not isinstance(index, Mapping):
                raise ValueError
            # SDK versions expose build parameters flattened or under params.
            build_params = index.get("params") or index
            if (
                index["field_name"] != "embedding"
                or index["index_type"] != self._config.MILVUS_INDEX_TYPE
                or index["metric_type"] != self._config.MILVUS_METRIC_TYPE
                or self._integer_parameter(build_params["M"]) != self._config.MILVUS_HNSW_M
                or self._integer_parameter(build_params["efConstruction"]) != self._config.MILVUS_HNSW_EF_CONSTRUCTION
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            raise VectorSpaceMismatchError() from None

    def _ensure_collection(self):
        with self._init_lock:
            if self._ready:
                return
            self._connect()
            exists = self._call("has_collection")
            if not isinstance(exists, bool):
                raise ServiceError("milvus", "invalid_response", status_code=502)
            if not exists:
                self._create_collection()
            self._read_config()
            self._ensure_index()
            self._call("load_collection")
            self._ready = True

    async def ensure_collection(self) -> None:
        await self._run(self._ensure_collection)

    async def get_collection_config(self) -> dict:
        def read():
            self._ensure_collection()
            return self._read_config()

        return await self._run(read)

    def _validate_text(self, name, value):
        try:
            if (
                not isinstance(value, str) or not value
                or len(value.encode("utf-8")) > self.STRING_LENGTHS[name]
            ):
                raise ValueError
        except (ValueError, UnicodeError):
            raise ServiceError("milvus", "invalid_request", status_code=422) from None
        return value

    def _validate_record(self, record):
        if not isinstance(record, Mapping) or set(record) != {*self.STRING_LENGTHS, "embedding"}:
            raise ServiceError("milvus", "invalid_request", status_code=422)
        result = {name: self._validate_text(name, record[name]) for name in self.STRING_LENGTHS}
        bucket, separator, key = result["tos_url"].removeprefix("tos://").partition("/")
        if (
            not result["tos_url"].startswith("tos://") or not bucket or not separator or not key
            or result["file_type"] not in ("image", "video")
        ):
            raise ServiceError("milvus", "invalid_request", status_code=422)
        result["embedding"] = self._validate_vector(record["embedding"])
        return result

    def _validate_vector(self, vector):
        try:
            return self._space.validate_vector(vector)
        except ServiceError:
            raise ServiceError("milvus", "invalid_vector", status_code=422) from None

    async def upsert(
        self, user_id: str, media_id: str, tos_url: str,
        file_type: str, embedding: Sequence[float],
    ) -> str:
        ids = await self.batch_upsert([{
            "user_id": user_id, "media_id": media_id, "tos_url": tos_url,
            "file_type": file_type, "embedding": embedding,
        }])
        return ids[0]

    async def batch_upsert(self, records: Sequence[VectorRecord]) -> List[str]:
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise ServiceError("milvus", "invalid_request", status_code=422)
        validated = [self._validate_record(record) for record in records]
        ids = [record["media_id"] for record in validated]
        # Last occurrence wins deterministically, including within one batch.
        data = list({record["media_id"]: record for record in validated}.values())

        def write():
            if not data:
                return []
            self._ensure_collection()
            response = self._call("upsert", data=data)
            if (
                not isinstance(response, Mapping)
                or type(response.get("upsert_count")) is not int
                or response["upsert_count"] != len(data)
            ):
                raise ServiceError("milvus", "invalid_response", status_code=502)
            return ids

        return await self._run(write)

    async def search(
        self, query_vector: Sequence[float], top_k: int = 20,
        min_score: float = 0.0, user_id: Optional[str] = None,
    ) -> List[VectorHit]:
        vector = self._validate_vector(query_vector)
        if user_id is not None:
            user_id = self._validate_text("user_id", user_id)
        if (
            type(top_k) is not int or not 1 <= top_k <= self.MAX_TOP_K
            or isinstance(min_score, bool) or not isinstance(min_score, Real)
            or not math.isfinite(min_score) or not 0 <= min_score <= 1
        ):
            raise ServiceError("milvus", "invalid_request", status_code=422)

        def find():
            self._ensure_collection()
            response = self._call(
                "search", data=[vector], anns_field="embedding", limit=top_k,
                output_fields=list(self.STRING_LENGTHS),
                filter=f"user_id == {json.dumps(user_id)}" if user_id else "",
                consistency_level=self._config.MILVUS_CONSISTENCY_LEVEL,
                search_params={
                    "metric_type": self._config.MILVUS_METRIC_TYPE,
                    "params": {"ef": max(top_k, self._config.MILVUS_SEARCH_EF)},
                },
            )
            try:
                if len(response) != 1 or not isinstance(response[0], list):
                    raise ValueError
                hits = []
                for hit in response[0]:
                    score = cosine_to_similarity(hit["distance"])
                    entity = hit["entity"]
                    primary_key = hit.get("media_id", hit.get("id"))
                    result = {
                        "media_id": primary_key, "user_id": entity["user_id"],
                        "tos_url": entity["tos_url"], "file_type": entity["file_type"],
                    }
                    if (
                        any(not isinstance(value, str) or not value for value in result.values())
                        or entity.get("media_id", primary_key) != primary_key
                    ):
                        raise ValueError
                    if score >= min_score:
                        hits.append({**result, "score": score})
                return sorted(hits, key=lambda hit: hit["score"], reverse=True)[:top_k]
            except (KeyError, TypeError, ValueError):
                raise ServiceError("milvus", "invalid_response", status_code=502) from None

        return await self._run(find)

    async def delete(self, media_id: str) -> None:
        media_id = self._validate_text("media_id", media_id)

        def remove():
            self._ensure_collection()
            # Use SDK PK encoding, never interpolate an expression.
            self._call("delete", ids=[media_id])

        await self._run(remove)

    async def get_vector_count(self, user_id: Optional[str] = None) -> int:
        if user_id is not None:
            user_id = self._validate_text("user_id", user_id)

        def count():
            self._ensure_collection()
            response = self._call(
                "query",
                filter=f"user_id == {json.dumps(user_id)}" if user_id else "",
                output_fields=["count(*)"],
                consistency_level=self._config.MILVUS_CONSISTENCY_LEVEL,
            )
            if (
                not isinstance(response, list) or len(response) != 1
                or not isinstance(response[0], Mapping)
                or type(response[0].get("count(*)")) is not int
                or response[0]["count(*)"] < 0
            ):
                raise ServiceError("milvus", "invalid_response", status_code=502)
            return response[0]["count(*)"]

        return await self._run(count)

    async def check_connection(self) -> dict:
        count = await self.get_vector_count()
        return {
            "service": "milvus", "status": "ready",
            "collection": self._space.collection, "vector_count": count,
            "count_is_exact": True,
            "consistency_level": self._config.MILVUS_CONSISTENCY_LEVEL,
        }

    async def _close(self):
        try:
            if self._pending:
                await asyncio.gather(*tuple(self._pending), return_exceptions=True)
            if self._client is not None:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="milvus")
                await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._safe_call, self._client.close,
                )
        finally:
            self._client = None
            if self._executor is not None:
                await asyncio.to_thread(partial(self._executor.shutdown, wait=True))

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)


milvus_service = MilvusService()
