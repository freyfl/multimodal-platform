"""Lazy TOS v2 SDK adapter. No client, executor or network activity on import."""

import asyncio
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from typing import Optional
from urllib.parse import unquote, urlsplit

import httpx

from app.config import settings
from app.errors import MissingConfigurationError, ServiceError
from app.utils.helpers import build_tos_url, is_image_file, is_video_file, parse_tos_url


_instance_cache = {}
_cache_lock = threading.Lock()
_CACHE_LIMIT = 64
_leases = {}
_closing_tasks = set()


def _close_in_background(instance):
    task = asyncio.create_task(instance.aclose())
    _closing_tasks.add(task)

    def finished(done):
        _closing_tasks.discard(done)
        if not done.cancelled():
            done.exception()

    task.add_done_callback(finished)
    return task


@asynccontextmanager
async def borrow_tos(user_settings):
    """Pin a client for an entire operation, including gaps between SDK calls.

    Streaming callers must keep this context alive until the response closes.
    """
    instance = TOSService.from_settings(user_settings)
    identity = id(instance)
    with _cache_lock:
        _, count = _leases.get(identity, (instance, 0))
        _leases[identity] = (instance, count + 1)
    try:
        yield instance
    finally:
        with _cache_lock:
            remaining = _leases[identity][1] - 1
            if remaining:
                _leases[identity] = (instance, remaining)
            else:
                del _leases[identity]
            close = not remaining and not any(
                cached is instance for cached in _instance_cache.values()
            )
        if close:
            await asyncio.shield(_close_in_background(instance))


def _https_endpoint(value: str) -> str:
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ServiceError("tos", "invalid_request", status_code=400)
    return f"https://{parsed.netloc}"


def _service_error(exc: Exception) -> ServiceError:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or not 400 <= status <= 599:
        status = 504 if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else 503
    category = {
        400: "invalid_request", 401: "authentication", 403: "permission",
        404: "not_found", 416: "invalid_request", 429: "rate_limit", 504: "timeout",
    }.get(status, "unavailable")
    return ServiceError(
        "tos", category, status_code=status,
        request_id=getattr(exc, "request_id", None),
        retryable=status == 429 or status >= 500,
    )


class _HTTPObjectStream:
    def __init__(self, response, owner):
        self._response = response
        self._owner = owner
        self._close_task = None
        self.status_code = response.status_code
        self.headers = dict(response.headers)

    async def aiter_bytes(self):
        try:
            # Preserve Content-Encoding/Content-Length by forwarding wire bytes.
            async for chunk in self._response.aiter_raw(chunk_size=65536):
                yield chunk
        except httpx.HTTPError as exc:
            raise _service_error(exc) from None
        finally:
            await self.aclose()

    async def _close(self):
        try:
            await self._response.aclose()
        finally:
            self._owner._streams.discard(self)

    async def aclose(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)


class TOSService:
    def __init__(
        self, access_key_id: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        bucket_name: Optional[str] = None, endpoint: Optional[str] = None,
        region: Optional[str] = None, custom_domain: Optional[str] = None,
        security_token: Optional[str] = None, *,
        client=None, client_factory=None, http_client=None, max_workers=None,
    ):
        values = {
            "access_key_id": access_key_id, "access_key_secret": access_key_secret,
            "bucket_name": bucket_name, "endpoint": endpoint, "region": region,
            "custom_domain": custom_domain, "security_token": security_token,
        }
        self._config = {
            key: getattr(settings, f"TOS_{key.upper()}") if value is None else value
            for key, value in values.items()
        }
        self._bucket_name = self._config["bucket_name"]
        self._client = client
        self._client_factory = client_factory
        self._client_lock = threading.Lock()
        self._http_client = http_client
        self._max_workers = settings.CLOUD_IO_MAX_WORKERS if max_workers is None else max_workers
        if self._max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._executor = None
        self._slots = None
        self._pending = set()
        self._streams = set()
        self._closed = False
        self._close_task = None

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    @classmethod
    def from_settings(cls, user_settings: dict) -> "TOSService":
        """Resolve a pooled client; runtime callers must use borrow_tos."""
        names = (
            "access_key_id", "access_key_secret", "bucket_name", "endpoint",
            "region", "custom_domain", "security_token",
        )
        # User operations never borrow deployment credentials for missing fields.
        values = {name: user_settings.get(f"tos_{name}") or "" for name in names}
        cache_key = tuple(values.values())
        with _cache_lock:
            instance = _instance_cache.pop(cache_key, None)
            if instance is not None and not instance._closed:
                _instance_cache[cache_key] = instance
                return instance
            instance = cls(**values)
            # Invalid/partial configurations must never occupy a cache slot.
            instance._validate_config()
            if len(_instance_cache) >= _CACHE_LIMIT:
                idle_key = next((
                    key for key, value in _instance_cache.items()
                    if id(value) not in _leases
                ), None)
                if idle_key is not None:
                    _close_in_background(_instance_cache.pop(idle_key))
            if len(_instance_cache) < _CACHE_LIMIT:
                _instance_cache[cache_key] = instance
            # If every slot is pinned, borrow_tos owns this temporary instance
            # and closes it on release instead of rejecting a valid user.
            return instance

    def _validate_config(self):
        required = ("access_key_id", "access_key_secret", "bucket_name", "endpoint", "region")
        missing = [
            f"TOS_{key.upper()}" for key in required
            if not isinstance(self._config[key], str) or not self._config[key].strip()
        ]
        if missing:
            raise MissingConfigurationError("tos", missing)
        try:
            build_tos_url(self._bucket_name, "")
        except ValueError:
            raise ServiceError("tos", "invalid_request", status_code=400) from None
        _https_endpoint(self._config["endpoint"])

    def _key(self, tos_url: str, *, allow_empty=False) -> str:
        self._validate_config()
        parsed = parse_tos_url(tos_url)
        if parsed is None or (not allow_empty and not parsed["path"]):
            raise ServiceError("tos", "invalid_request", status_code=400)
        if parsed["bucket"] != self._bucket_name:
            raise ServiceError("tos", "permission", status_code=403)
        return parsed["path"]

    def _get_client(self):
        with self._client_lock:
            if self._client is None:
                factory = self._client_factory
                if factory is None:
                    from tos import TosClientV2
                    factory = TosClientV2
                self._client = factory(
                    ak=self._config["access_key_id"],
                    sk=self._config["access_key_secret"],
                    security_token=self._config["security_token"] or None,
                    endpoint=_https_endpoint(self._config["endpoint"]),
                    region=self._config["region"],
                    max_connections=self._max_workers,
                    max_retry_count=2, connection_time=10, socket_timeout=30,
                )
            return self._client

    async def _run(self, operation):
        if self._closed:
            raise ServiceError("tos", "unavailable")
        self._validate_config()
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="tos",
            )
            self._slots = asyncio.Semaphore(self._max_workers)
        await self._slots.acquire()
        if self._closed:
            self._slots.release()
            raise ServiceError("tos", "unavailable")

        def invoke():
            try:
                return operation(self._get_client())
            except ServiceError:
                raise
            except Exception as exc:
                raise _service_error(exc) from None

        future = asyncio.get_running_loop().run_in_executor(self._executor, invoke)
        self._pending.add(future)

        def completed(done):
            self._pending.discard(done)
            self._slots.release()
            if not done.cancelled():
                done.exception()

        future.add_done_callback(completed)
        # A cancelled coroutine cannot release a slot until its SDK call finishes.
        return await asyncio.shield(future)

    async def list_files(self, directory: str) -> list:
        prefix = self._key(directory, allow_empty=True)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        files, token, seen = [], None, set()
        while True:
            result = await self._run(lambda client: client.list_objects_type2(
                bucket=self._bucket_name, prefix=prefix, max_keys=1000,
                continuation_token=token, list_only_once=True, encoding_type="url",
            ))
            for obj in result.contents:
                # TOS ListObjectType2Output keeps EncodingType=url keys encoded.
                key = unquote(obj.key, encoding="utf-8", errors="strict")
                filename = key.rsplit("/", 1)[-1]
                if not filename:
                    continue
                file_type = "video" if is_video_file(filename) else (
                    "image" if is_image_file(filename) else None
                )
                if file_type:
                    files.append({
                        "tos_url": build_tos_url(self._bucket_name, key),
                        "file_name": filename, "file_size": obj.size,
                        "file_type": file_type,
                    })
            if not result.is_truncated:
                return files
            token = result.next_continuation_token
            if not token or token in seen:
                raise ServiceError("tos", "invalid_response", status_code=502)
            seen.add(token)

    async def file_exists(self, tos_url: str) -> bool:
        key = self._key(tos_url)
        try:
            await self._run(lambda client: client.head_object(bucket=self._bucket_name, key=key))
            return True
        except ServiceError as exc:
            if exc.status_code == 404:
                return False
            raise

    async def _sign(self, tos_url, expires, method, custom=False):
        key = self._key(tos_url)
        if type(expires) is not int or not 1 <= expires <= 604800:
            raise ServiceError("tos", "invalid_request", status_code=400)

        def sign(client):
            from tos.enum import HttpMethodType
            kwargs = {}
            if custom and self._config["custom_domain"]:
                parameters = inspect.signature(client.pre_signed_url).parameters
                if {"alternative_endpoint", "is_custom_domain"} <= parameters.keys():
                    kwargs = {
                        "alternative_endpoint": _https_endpoint(self._config["custom_domain"]),
                        "is_custom_domain": True,
                    }
            result = client.pre_signed_url(
                http_method=(
                    HttpMethodType.Http_Method_Head if method == "HEAD"
                    else HttpMethodType.Http_Method_Get
                ),
                bucket=self._bucket_name, key=key, expires=expires, **kwargs,
            )
            url = result.signed_url
            if urlsplit(url).scheme != "https":
                raise ServiceError("tos", "invalid_response", status_code=502)
            return url

        return await self._run(sign)

    async def get_file_url(self, tos_url: str, expires: int = 3600) -> str:
        return await self._sign(tos_url, expires, "GET")

    async def get_preview_url(self, tos_url: str, expires: int = 3600) -> str:
        return await self._sign(tos_url, expires, "GET", custom=True)

    async def upload_file(self, local_path: str, tos_path: str) -> bool:
        """tos_path is a canonical URI, including the effective bucket."""
        key = self._key(tos_path)
        await self._run(lambda client: client.put_object_from_file(
            bucket=self._bucket_name, key=key, file_path=local_path,
        ))
        return True

    async def download_file(self, tos_url: str, local_path: str) -> bool:
        key = self._key(tos_url)
        await self._run(lambda client: client.get_object_to_file(
            bucket=self._bucket_name, key=key, file_path=local_path,
        ))
        return True

    async def delete_file(self, tos_url: str) -> None:
        key = self._key(tos_url)
        await self._run(lambda client: client.delete_object(bucket=self._bucket_name, key=key))

    async def open_object(
        self, tos_url: str, *, method: str = "GET", range_header: Optional[str] = None,
    ):
        if method not in ("GET", "HEAD"):
            raise ServiceError("tos", "invalid_request", status_code=400)
        signed_url = await self._sign(tos_url, settings.TOS_SIGNED_URL_EXPIRES, method)
        if self._closed:
            raise ServiceError("tos", "unavailable")
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=120, follow_redirects=False,
                limits=httpx.Limits(max_connections=self._max_workers),
            )
        headers = {"Accept-Encoding": "identity"}
        if range_header:
            headers["Range"] = range_header
        try:
            response = await self._http_client.send(
                self._http_client.build_request(method, signed_url, headers=headers), stream=True,
            )
        except httpx.HTTPError as exc:
            raise _service_error(exc) from None
        stream = _HTTPObjectStream(response, self)
        self._streams.add(stream)
        if self._closed:
            await stream.aclose()
            raise ServiceError("tos", "unavailable")
        return stream

    async def check_connection(self) -> dict:
        await self._run(lambda client: client.head_bucket(bucket=self._bucket_name))
        return {"service": "tos", "status": "ready"}

    async def _close(self):
        self._closed = True
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        try:
            await asyncio.gather(*(stream.aclose() for stream in tuple(self._streams)))
        finally:
            try:
                if self._http_client is not None:
                    await self._http_client.aclose()
            finally:
                try:
                    if self._client is not None:
                        await asyncio.to_thread(self._client.close)
                finally:
                    if self._executor is not None:
                        await asyncio.to_thread(partial(self._executor.shutdown, wait=True))

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)


tos_service = TOSService()


async def close_tos_services() -> None:
    """Lifespan hook; closes the global service and all cached user clients."""
    with _cache_lock:
        instances = {
            id(instance): instance
            for instance in [
                tos_service, *_instance_cache.values(),
                *(value[0] for value in _leases.values()),
            ]
        }.values()
        _instance_cache.clear()
    await asyncio.gather(
        *(instance.aclose() for instance in instances), *tuple(_closing_tasks),
    )
