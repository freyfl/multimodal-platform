"""User TOS/Ark settings and explicit, potentially billable model probes."""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SECRET_SETTING_FIELDS, USER_SETTING_FIELDS, effective_user_settings,
    get_current_user, get_user_settings_row, require_admin,
)
from app.errors import ServiceError
from app.models.database import get_session
from app.models.schemas import ApiResponse, UserSettingsResponse, UserSettingsUpdate
from app.services.embedding_service import embedding_service
from app.services.tag_service import tag_service
from app.services.tos_service import TOSService

router = APIRouter(prefix="/settings", tags=["用户配置"])


def _ensure_self_service_allowed(current_user: dict) -> None:
    if current_user.get("is_demo") == 1:
        raise HTTPException(status_code=403, detail="演示账号配置由管理员维护")


async def _ensure_target_user(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(
        text("SELECT id, is_demo FROM users WHERE id = :uid"),
        {"uid": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return dict(row._mapping)


def _build_response(user_id: str, row: dict | None = None) -> dict:
    cfg = effective_user_settings(row)
    data = {key: cfg[key] for key in USER_SETTING_FIELDS if key not in SECRET_SETTING_FIELDS}
    data.update({
        f"{key}_masked": "****" if cfg[key] else None
        for key in SECRET_SETTING_FIELDS
    })
    row = row or {}
    data.update(
        id=row.get("id", ""), user_id=user_id,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )
    return UserSettingsResponse(**data).model_dump()


@router.get("/me", response_model=ApiResponse)
async def get_my_settings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    row = await get_user_settings_row(db, current_user["id"])
    return ApiResponse(data=_build_response(current_user["id"], row))


@router.put("/me", response_model=ApiResponse)
async def update_my_settings(
    body: UserSettingsUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _ensure_self_service_allowed(current_user)
    return await _update_settings(current_user["id"], body, db)


async def _update_settings(
    user_id: str, body: UserSettingsUpdate, db: AsyncSession,
) -> ApiResponse:
    existing = await get_user_settings_row(db, user_id)
    changes = body.updates()
    effective_user_settings(existing, changes)
    if not changes:
        return ApiResponse(message="无需更新", data=_build_response(user_id, existing))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        if existing:
            params = {**changes, "updated_at": now}
            assignments = ", ".join(f"{name} = :{name}" for name in params)
            await db.execute(
                text(f"UPDATE user_system_settings SET {assignments} WHERE user_id = :uid"),
                {**params, "uid": user_id},
            )
        else:
            params = {
                "id": str(uuid.uuid4()), "user_id": user_id,
                **changes, "created_at": now, "updated_at": now,
            }
            columns = ", ".join(params)
            values = ", ".join(f":{name}" for name in params)
            await db.execute(
                text(f"INSERT INTO user_system_settings ({columns}) VALUES ({values})"),
                params,
            )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise ServiceError("mysql", "unavailable") from None

    updated = await get_user_settings_row(db, user_id)
    return ApiResponse(message="配置已保存", data=_build_response(user_id, updated))


@router.delete("/me", response_model=ApiResponse)
async def delete_my_settings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _ensure_self_service_allowed(current_user)
    return await _delete_settings(current_user["id"], db)


async def _delete_settings(user_id: str, db: AsyncSession) -> ApiResponse:
    try:
        await db.execute(
            text("DELETE FROM user_system_settings WHERE user_id = :uid"),
            {"uid": user_id},
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise ServiceError("mysql", "unavailable") from None
    return ApiResponse(
        message="配置已删除",
        data=_build_response(user_id),
    )


async def _probe(service_name: str, check) -> dict:
    """Never serialize SDK/model payloads, even from a failed probe."""
    try:
        result = await check()
        if not isinstance(result, dict):
            raise ServiceError(service_name, "invalid_response")
        if result.get("success") is False or (
            result.get("status") not in ("ok", "ready") and result.get("success") is not True
        ):
            raise ServiceError(service_name, "unavailable")
        return {"success": True, "error": None}
    except ServiceError as error:
        return {"success": False, "error": error.to_dict()}
    except Exception:
        return {"success": False, "error": ServiceError(service_name, "unavailable").to_dict()}


@router.post("/me/test-tos", response_model=ApiResponse)
async def test_tos_connection(
    body: UserSettingsUpdate | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _ensure_self_service_allowed(current_user)
    return await _test_tos(current_user["id"], body, db)


async def _test_tos(
    user_id: str, body: UserSettingsUpdate | None, db: AsyncSession,
) -> ApiResponse:
    saved = await get_user_settings_row(db, user_id)
    cfg = effective_user_settings(saved, body.updates() if body else None)

    async def check():
        service = TOSService(
            access_key_id=cfg["tos_access_key_id"] or "",
            access_key_secret=cfg["tos_access_key_secret"] or "",
            security_token=cfg["tos_security_token"] or "",
            bucket_name=cfg["tos_bucket_name"] or "",
            endpoint=cfg["tos_endpoint"] or "",
            region=cfg["tos_region"] or "",
            custom_domain=cfg["tos_custom_domain"] or "",
        )
        try:
            return await service.check_connection()
        finally:
            await service.aclose()

    result = await _probe("tos", check)
    return ApiResponse(
        code=200 if result["success"] else 503,
        message="TOS 连接成功" if result["success"] else "TOS 连接失败",
        data=result,
    )


@router.post("/me/test-ark", response_model=ApiResponse)
async def test_ark_connection(
    body: UserSettingsUpdate | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _ensure_self_service_allowed(current_user)
    return await _test_ark(current_user["id"], body, db)


async def _test_ark(
    user_id: str, body: UserSettingsUpdate | None, db: AsyncSession,
) -> ApiResponse:
    saved = await get_user_settings_row(db, user_id)
    cfg = effective_user_settings(saved, body.updates() if body else None)
    embedding, tag = await asyncio.gather(
        _probe("ark", lambda: embedding_service.check_connection(api_key=cfg["ark_api_key"] or "")),
        _probe("ark", lambda: tag_service.check_connection(api_key=cfg["ark_api_key"] or "")),
    )
    success = embedding["success"] and tag["success"]
    return ApiResponse(
        code=200 if success else 503,
        message="方舟两个模型连接成功" if success else "方舟模型连接测试未全部通过",
        data={"success": success, "embedding": embedding, "tag": tag},
    )


@router.get("/users/{user_id}", response_model=ApiResponse)
async def get_user_settings_as_admin(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_target_user(db, user_id)
    row = await get_user_settings_row(db, user_id)
    return ApiResponse(data=_build_response(user_id, row))


@router.put("/users/{user_id}", response_model=ApiResponse)
async def update_user_settings_as_admin(
    user_id: str,
    body: UserSettingsUpdate,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_target_user(db, user_id)
    return await _update_settings(user_id, body, db)


@router.delete("/users/{user_id}", response_model=ApiResponse)
async def delete_user_settings_as_admin(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_target_user(db, user_id)
    return await _delete_settings(user_id, db)


@router.post("/users/{user_id}/test-tos", response_model=ApiResponse)
async def test_user_tos_as_admin(
    user_id: str,
    body: UserSettingsUpdate | None = None,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_target_user(db, user_id)
    return await _test_tos(user_id, body, db)


@router.post("/users/{user_id}/test-ark", response_model=ApiResponse)
async def test_user_ark_as_admin(
    user_id: str,
    body: UserSettingsUpdate | None = None,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_target_user(db, user_id)
    return await _test_ark(user_id, body, db)
