"""Lazy Ark HTTP transport shared by Responses and multimodal embeddings.

Protocol references (checked 2026-09-17):
https://www.volcengine.com/docs/82379/1569618 (input_video/video_url string)
https://www.volcengine.com/docs/82379/1409291 (embeddings, Base64 images)
https://www.volcengine.com/docs/82379/1362931 (data URI encoding)
These document the protocol, not account access to the configured Seed version.
"""

import asyncio
import base64
import binascii
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import unquote, urlsplit

import httpx

from app.config import Settings, settings
from app.errors import MissingConfigurationError, ServiceError


_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".apng", ".gif", ".webp", ".bmp", ".tif",
    ".tiff", ".ico", ".dib", ".icns", ".sgi", ".j2c", ".j2k", ".jp2",
    ".jpc", ".jpf", ".jpx",
}
_IMAGE_MIMES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
    "image/tiff", "image/x-icon", "image/icns", "image/sgi", "image/jp2",
}
_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/avi"}


def strict_json_loads(text: str):
    def reject_constant(value):
        raise ValueError("Non-finite JSON constant")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def invalid_response(request_id: Optional[str] = None) -> ServiceError:
    return ServiceError("ark", "invalid_response", request_id=request_id, status_code=502)


def media_kind(url: str) -> str:
    """Determine modality from the stable object URI, not its signing query."""
    try:
        if url.startswith("data:image/"):
            return "image"
        if url.startswith("data:video/"):
            return "video"
        # TOS keys may contain literal # or ?, unlike an HTTPS signing query.
        path = url.split("/", 3)[3] if url.startswith("tos://") else urlsplit(url).path
        suffix = PurePosixPath(unquote(path)).suffix.lower()
        if suffix in {".mp4", ".avi", ".mov"}:
            return "video"
        if suffix in _IMAGE_EXTENSIONS:
            return "image"
    except (AttributeError, IndexError, TypeError, ValueError):
        pass
    raise ServiceError("ark", "invalid_request", status_code=400)


def validate_media_url(url: str, kind: str) -> str:
    """Preserve signed URLs/data URIs verbatim; never fetch media locally."""
    try:
        if not isinstance(url, str) or not url:
            raise ValueError
        if url.startswith("data:"):
            header, payload = url.split(",", 1)
            allowed = _IMAGE_MIMES if kind == "image" else _VIDEO_MIMES
            if header not in {f"data:{mime};base64" for mime in allowed}:
                raise ValueError
            limit = (10 if kind == "image" else 50) * 1024 * 1024
            if len(payload) > 4 * ((limit + 2) // 3):
                raise ValueError
            decoded = base64.b64decode(payload, validate=True)
            if not decoded or len(decoded) >= limit:
                raise ValueError
        else:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password
                or any(ord(char) < 32 or ord(char) == 127 for char in url)
            ):
                raise ValueError
    except (ValueError, TypeError, binascii.Error):
        raise ServiceError("ark", "invalid_request", status_code=400) from None
    return url


def response_text(data: dict) -> str:
    """Only completed assistant output_text is an answer; reasoning is ignored."""
    request_id = data.get("id")
    if (
        data.get("status") != "completed" or data.get("error") is not None
        or data.get("incomplete_details") is not None
        or not isinstance(data.get("output"), list)
    ):
        raise invalid_response(request_id)
    parts = []
    for item in data["output"]:
        if not isinstance(item, dict):
            raise invalid_response(request_id)
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        if item.get("status") != "completed" or not isinstance(item.get("content"), list):
            raise invalid_response(request_id)
        for content in item["content"]:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                raise invalid_response(request_id)
            if not isinstance(content.get("text"), str):
                raise invalid_response(request_id)
            parts.append(content["text"])
    text = "".join(parts)
    if not text.strip():
        raise invalid_response(request_id)
    return text


class ArkClient:
    """Per-instance concurrency budget; inject one instance to share the budget.

    Injected httpx clients are borrowed and closed by their owner. Clients made
    here are lazy and closed by aclose(). API keys are per-request, never globals.
    """

    def __init__(self, *, config: Optional[Settings] = None,
                 http_client: Optional[httpx.AsyncClient] = None):
        self.config = config or settings
        self._client = http_client
        self._owns_client = http_client is None
        self._semaphore = asyncio.Semaphore(self.config.ARK_MAX_CONCURRENCY)
        self._closed = False

    def _connection(self, api_key: Optional[str]):
        key = self.config.ARK_API_KEY if api_key is None else api_key
        missing = []
        if not isinstance(key, str) or not key.strip():
            missing.append("ARK_API_KEY")
        if not self.config.ARK_BASE_URL.strip():
            missing.append("ARK_BASE_URL")
        if missing:
            raise MissingConfigurationError("ark", missing)
        try:
            base = urlsplit(self.config.ARK_BASE_URL)
            if (
                base.scheme != "https" or not base.hostname or base.username
                or base.password or base.query or base.fragment
                or any(ord(char) < 33 or ord(char) > 126 for char in key)
            ):
                raise ValueError
        except ValueError:
            raise ServiceError("ark", "invalid_request", status_code=400) from None
        if self._closed:
            raise ServiceError("ark", "unavailable")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.ARK_REQUEST_TIMEOUT,
                limits=httpx.Limits(
                    max_connections=self.config.ARK_MAX_CONCURRENCY,
                    max_keepalive_connections=self.config.ARK_MAX_CONCURRENCY,
                ),
                follow_redirects=False,
            )
        return key, self.config.ARK_BASE_URL.rstrip("/")

    def _retry_delay(self, attempt: int, retry_after: Optional[str]) -> Optional[float]:
        maximum = self.config.ARK_RETRY_MAX_DELAY
        delay = min(self.config.ARK_RETRY_BASE_DELAY * 2 ** attempt, maximum)
        if retry_after:
            try:
                try:
                    requested = float(retry_after)
                except ValueError:
                    date = parsedate_to_datetime(retry_after)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    requested = (date - datetime.now(timezone.utc)).total_seconds()
                if math.isfinite(requested):
                    # Do not retry earlier than the server permits. A very long
                    # cooldown is handed back to the caller as retryable failure.
                    if requested > maximum:
                        return None
                    delay = max(delay, requested)
            except (ValueError, TypeError, OverflowError):
                pass
        return delay

    async def post(self, path: str, payload: dict, *, api_key: Optional[str] = None) -> dict:
        if path not in {"/responses", "/embeddings/multimodal"}:
            raise ServiceError("ark", "invalid_request", status_code=400)
        key, base = self._connection(api_key)
        for attempt in range(self.config.ARK_MAX_RETRIES + 1):
            retry_after = None
            try:
                async with asyncio.timeout(self.config.ARK_REQUEST_TIMEOUT):
                    async with self._semaphore:
                        if self._closed:
                            raise ServiceError("ark", "unavailable")
                        response = await self._client.post(
                            base + path, json=payload,
                            headers={"Authorization": f"Bearer {key}"},
                            timeout=self.config.ARK_REQUEST_TIMEOUT,
                            follow_redirects=False,
                        )
            except (httpx.TimeoutException, TimeoutError):
                error = ServiceError("ark", "timeout", retryable=True, status_code=504)
            except httpx.TransportError:
                error = ServiceError("ark", "unavailable", retryable=True)
            except (httpx.InvalidURL, ValueError):
                raise ServiceError("ark", "invalid_request", status_code=400) from None
            else:
                request_id = response.headers.get("x-request-id") or response.headers.get("x-tt-logid")
                if 200 <= response.status_code < 300:
                    try:
                        data = strict_json_loads(response.text)
                    except (ValueError, UnicodeError, RecursionError):
                        raise invalid_response(request_id) from None
                    if not isinstance(data, dict) or data.get("error") is not None:
                        raise invalid_response(request_id)
                    if data.get("model", payload.get("model")) != payload.get("model"):
                        raise invalid_response(request_id or data.get("id"))
                    if request_id and not data.get("id"):
                        data["id"] = request_id
                    return data
                status = response.status_code
                retryable = status in {408, 429, 500, 502, 503, 504}
                category = {
                    401: "authentication", 403: "permission", 404: "not_found",
                    408: "timeout", 429: "rate_limit",
                }.get(status, "unavailable" if status >= 500 else "invalid_request")
                error = ServiceError(
                    "ark", category, request_id=request_id,
                    retryable=retryable, status_code=status if status >= 400 else 502,
                )
                retry_after = response.headers.get("retry-after")
            if not error.retryable or attempt == self.config.ARK_MAX_RETRIES:
                raise error from None
            delay = self._retry_delay(attempt, retry_after)
            if delay is None:
                raise error from None
            await asyncio.sleep(delay)

    async def aclose(self) -> None:
        self._closed = True
        if self._owns_client and self._client is not None:
            await self._client.aclose()


# Module import allocates no HTTP client and performs no network I/O.
ark_client = ArkClient()
