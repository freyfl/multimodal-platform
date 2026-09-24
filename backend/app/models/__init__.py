"""Schema imports must not initialize the database."""

from importlib import import_module

from app.models.schemas import (
    ApiResponse,
    MAX_CUSTOM_TAG_PROMPT_LENGTH, TagSource,
    FileType, TaskStatus, VectorStatus,
    ImportStartRequest, ImportTaskResponse, ImportTaskDetail, ImportTaskListResponse,
    TagIdentity, TagSearchRequest, TextSearchRequest, ImageSearchRequest,
    SearchResultItem, SearchResponse,
    TagSystemResponse, TagUpdateRequest, TagItem,
    SystemStats, HealthCheck,
    UserCreate, UserLogin, UserResponse, TokenResponse,
    RefreshRequest, PasswordChange, UserUpdate, PaginatedUsers,
    UserSettingsUpdate, UserSettingsResponse, ModelCatalog, PublicSystemConfig,
)

__all__ = [
    "Base", "engine", "async_session_maker", "init_db", "get_session",
    "MediaFile", "MediaTag", "ImportTask", "SearchHistory",
    "AnnotationRun", "AnnotationFrame", "AnnotationResultSet", "AnnotationResultSetMember",
    "User", "LoginLog", "UserSession", "UserSystemSettings",
    "ApiResponse",
    "MAX_CUSTOM_TAG_PROMPT_LENGTH", "TagSource",
    "FileType", "TaskStatus", "VectorStatus",
    "ImportStartRequest", "ImportTaskResponse", "ImportTaskDetail", "ImportTaskListResponse",
    "TagIdentity", "TagSearchRequest", "TextSearchRequest", "ImageSearchRequest",
    "SearchResultItem", "SearchResponse",
    "TagSystemResponse", "TagUpdateRequest", "TagItem",
    "SystemStats", "HealthCheck",
    "UserCreate", "UserLogin", "UserResponse", "TokenResponse",
    "RefreshRequest", "PasswordChange", "UserUpdate", "PaginatedUsers",
    "UserSettingsUpdate", "UserSettingsResponse", "ModelCatalog", "PublicSystemConfig",
]


def __getattr__(name):
    if name in {"Base", "engine", "async_session_maker", "init_db", "get_session"}:
        return getattr(import_module("app.models.database"), name)
    if name in {
        "MediaFile", "MediaTag", "ImportTask", "SearchHistory", "User", "LoginLog",
        "UserSession", "UserSystemSettings", "AnnotationRun", "AnnotationFrame",
        "AnnotationResultSet", "AnnotationResultSetMember",
    }:
        return getattr(import_module("app.models.models"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
