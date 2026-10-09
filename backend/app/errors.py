"""Public errors contain only allow-listed metadata, never upstream bodies."""

import re
from typing import Iterable, Optional


_MESSAGES = {
    "not_configured": "Required service configuration is missing",
    "authentication": "Service authentication failed",
    "permission": "Service access was denied",
    "not_found": "Requested resource was not found",
    "invalid_request": "Service request is invalid",
    "timeout": "Service request timed out",
    "rate_limit": "Service rate limit exceeded",
    "unavailable": "Service is unavailable",
    "invalid_response": "Service returned an invalid response",
    "invalid_vector": "Vector must be finite, nonzero and match the configured dimension",
    "incompatible_vector_space": "Vector space differs; use an explicitly rebuilt collection",
}
_SERVICES = {"tos", "ark", "milvus", "mysql", "application"}


class ServiceError(RuntimeError):
    """Safe to serialize and log; do not attach an upstream exception message.

    Catch SDK/HTTP errors and raise this error ``from None`` at API boundaries.
    Never log request headers, signed URLs, response bodies or chained exceptions.
    """

    def __init__(
        self,
        service: str,
        category: str,
        *,
        request_id: Optional[str] = None,
        retryable: bool = False,
        status_code: int = 503,
        missing_fields: Iterable[str] = (),
    ):
        self.service = service if service in _SERVICES else "application"
        self.category = category if category in _MESSAGES else "unavailable"
        self.request_id = (
            request_id
            if isinstance(request_id, str)
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id)
            else None
        )
        self.retryable = retryable
        self.status_code = status_code
        self.missing_fields = tuple(
            field for field in missing_fields
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", field)
        )
        self.message = _MESSAGES[self.category]
        super().__init__(f"{self.service}: {self.message}")

    def to_dict(self) -> dict:
        result = {
            "service": self.service,
            "category": self.category,
            "message": self.message,
            "retryable": self.retryable,
            "request_id": self.request_id,
        }
        if self.missing_fields:
            result["missing_fields"] = list(self.missing_fields)
        return result


class MissingConfigurationError(ServiceError):
    def __init__(self, service: str, fields: Iterable[str]):
        super().__init__(service, "not_configured", missing_fields=fields)


class VectorSpaceMismatchError(ServiceError):
    def __init__(self):
        super().__init__("milvus", "incompatible_vector_space", status_code=409)
