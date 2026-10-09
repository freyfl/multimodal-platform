"""
认证路由模块
登录、注册、刷新 Token、注销、个人信息、修改密码
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import get_session
from app.models.schemas import (
    ApiResponse, UserCreate, UserLogin, UserResponse,
    TokenResponse, RefreshRequest, PasswordChange,
)
from app.services import auth_service
from app.api.deps import get_current_user
from app.utils.logger import logger

router = APIRouter(prefix="/auth", tags=["认证"])


# ---------- helpers ----------

def _user_response(user: dict) -> UserResponse:
    """将 user dict 转换为 UserResponse"""
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user.get("email"),
        role=user["role"],
        is_demo=user.get("is_demo", 0),
        is_active=user.get("is_active", 1),
        created_at=user.get("created_at"),
    )


def _extract_client_info(request: Request):
    """从 Request 中提取 IP 和 User-Agent"""
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not ip:
        ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    return ip, ua


# ---------- routes ----------

@router.post("/login", response_model=ApiResponse)
async def login(
    body: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """用户登录"""
    settings.require_config("application")
    ip, ua = _extract_client_info(request)

    user = await auth_service.authenticate_user(db, body.username, body.password)
    if not user:
        # 尝试获取 user_id 用于失败日志
        try:
            result = await db.execute(
                text("SELECT id FROM users WHERE username = :u"),
                {"u": body.username},
            )
            row = result.fetchone()
            uid = dict(row._mapping)["id"] if row else "unknown"
        except Exception:
            await db.rollback()
            uid = "unknown"
        try:
            await auth_service.log_login(db, uid, ip, ua, "failed")
        except Exception:
            await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 生成 token
    access_token = auth_service.create_access_token(user["id"], user["username"], user["role"])
    refresh_token = auth_service.create_refresh_token(user["id"])

    # 创建 session
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    await auth_service.create_session(db, user["id"], refresh_token, expires_at)

    # 记录登录日志
    try:
        await auth_service.log_login(db, user["id"], ip, ua, "success")
    except Exception:
        await db.rollback()
        logger.warning("记录登录日志失败")

    return ApiResponse(data=TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_response(user),
    ).model_dump())


@router.post("/register", response_model=ApiResponse)
async def register(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """用户注册"""
    settings.require_config("application")
    if not settings.ALLOW_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="注册功能已关闭",
        )

    try:
        user = await auth_service.register_user(
            db,
            username=body.username,
            password=body.password,
            email=body.email,
            role="user",  # 普通注册只能是 user
            is_demo=0,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    # 自动登录
    access_token = auth_service.create_access_token(user["id"], user["username"], user["role"])
    refresh_token = auth_service.create_refresh_token(user["id"])

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    await auth_service.create_session(db, user["id"], refresh_token, expires_at)

    ip, ua = _extract_client_info(request)
    try:
        await auth_service.log_login(db, user["id"], ip, ua, "success")
    except Exception:
        await db.rollback()
        logger.warning("记录登录日志失败")

    return ApiResponse(data=TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_response(user),
    ).model_dump())


@router.post("/refresh", response_model=ApiResponse)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_session),
):
    """刷新 access token"""
    try:
        new_access = await auth_service.refresh_access_token(db, body.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    return ApiResponse(data={
        "access_token": new_access,
        "token_type": "bearer",
    })


@router.post("/logout", response_model=ApiResponse)
async def logout(
    body: RefreshRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """注销（吊销 refresh token 对应的 session）"""
    await auth_service.revoke_session(db, body.refresh_token)
    return ApiResponse(message="已注销")


@router.get("/me", response_model=ApiResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return ApiResponse(data=_user_response(current_user).model_dump())


@router.put("/me/password", response_model=ApiResponse)
async def change_password(
    body: PasswordChange,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """修改密码"""
    if current_user.get("is_demo") == 1:
        raise HTTPException(status_code=403, detail="演示账号不允许修改密码")
    # 验证旧密码
    result = await db.execute(
        text("SELECT password_hash FROM users WHERE id = :id"),
        {"id": current_user["id"]},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not auth_service.verify_password(body.old_password, dict(row._mapping)["password_hash"]):
        raise HTTPException(status_code=400, detail="旧密码错误")

    # 更新密码
    new_hash = auth_service.hash_password(body.new_password)
    await db.execute(
        text("UPDATE users SET password_hash = :ph, updated_at = :now WHERE id = :id"),
        {
            "ph": new_hash,
            "now": datetime.now(timezone.utc).replace(tzinfo=None),
            "id": current_user["id"],
        },
    )
    # Password update and session revocation commit together.
    await auth_service.revoke_all_user_sessions(db, current_user["id"])

    return ApiResponse(message="密码修改成功，请重新登录")
