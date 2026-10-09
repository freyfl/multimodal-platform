"""
认证依赖注入模块
提供 get_current_user / require_admin 用于路由保护
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import ServiceError, VectorSpaceMismatchError
from app.models.database import get_session
from app.services.auth_service import verify_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """从 Bearer token 解析当前用户，返回用户 dict"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = verify_token(token)
    except ServiceError:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 类型错误",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 缺少用户信息",
        )

    try:
        result = await db.execute(
            text(
                "SELECT id, username, email, role, is_demo, is_active, created_at "
                "FROM users WHERE id = :id"
            ),
            {"id": user_id},
        )
    except SQLAlchemyError:
        raise ServiceError("mysql", "unavailable") from None
    row = result.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    user = dict(row._mapping)
    if user.get("is_active", 1) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """要求管理员角色"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


USER_SETTING_FIELDS = (
    "tos_access_key_id", "tos_access_key_secret", "tos_security_token",
    "tos_bucket_name", "tos_endpoint", "tos_region", "tos_custom_domain",
    "ark_api_key", "embedding_model", "embedding_dimension", "tag_model",
)
SECRET_SETTING_FIELDS = (
    "tos_access_key_id", "tos_access_key_secret", "tos_security_token", "ark_api_key",
)


def effective_user_settings(saved: dict | None = None, overrides: dict | None = None) -> dict:
    """Resolve an isolated user configuration without deployment credentials."""
    cfg = {name: None for name in USER_SETTING_FIELDS}
    cfg.update(
        embedding_model=settings.ARK_EMBEDDING_MODEL,
        embedding_dimension=settings.EMBEDDING_DIMENSION,
        tag_model=settings.ARK_TAG_MODEL,
    )
    for source in (saved or {}, overrides or {}):
        for name in USER_SETTING_FIELDS:
            if name not in source or source[name] is None:
                continue
            value = source[name]
            if name in SECRET_SETTING_FIELDS and (
                not isinstance(value, str) or not value.strip()
            ):
                continue
            cfg[name] = value
    if (
        cfg["embedding_model"] != settings.ARK_EMBEDDING_MODEL
        or type(cfg["embedding_dimension"]) is not int
        or cfg["embedding_dimension"] != settings.EMBEDDING_DIMENSION
    ):
        raise VectorSpaceMismatchError()
    if cfg["tag_model"] != settings.ARK_TAG_MODEL:
        raise ServiceError("ark", "invalid_request", status_code=400)
    cfg["is_custom"] = saved is not None or bool(overrides)
    return cfg


def effective_deployment_settings() -> dict:
    """Deployment credentials are reserved for infrastructure/admin legacy access."""
    cfg = {
        name: getattr(settings, name.upper())
        for name in USER_SETTING_FIELDS
        if name not in {"embedding_model", "tag_model"}
    }
    cfg.update(
        embedding_model=settings.ARK_EMBEDDING_MODEL,
        tag_model=settings.ARK_TAG_MODEL,
        is_custom=True,
    )
    return cfg


async def get_user_settings_row(db: AsyncSession, user_id: str) -> dict | None:
    columns = ", ".join(("id", "user_id", *USER_SETTING_FIELDS, "created_at", "updated_at"))
    try:
        result = await db.execute(
            text(f"SELECT {columns} FROM user_system_settings WHERE user_id = :uid"),
            {"uid": user_id},
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None
    except SQLAlchemyError:
        raise ServiceError("mysql", "unavailable") from None


async def get_user_settings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Return effective credentials internally; response routes must mask them."""
    saved = await get_user_settings_row(db, current_user["id"])
    return effective_user_settings(saved)
