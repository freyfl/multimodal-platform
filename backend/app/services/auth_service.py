"""
认证服务模块
密码哈希、JWT Token 管理、用户操作、会话管理
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from jose import jwt, JWTError, ExpiredSignatureError
import bcrypt
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import User, UserSession
from app.utils.logger import logger

# ==================== 密码管理 ====================


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希值是否匹配"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# ==================== JWT Token 管理 ====================

ALGORITHM = "HS256"


def create_access_token(user_id: str, username: str, role: str) -> str:
    """创建 access token"""
    settings.require_config("application")
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """创建 refresh token"""
    settings.require_config("application")
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """验证并解码 JWT，返回 payload 或抛出异常"""
    settings.require_config("application")
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])


# ==================== 用户操作 ====================

async def register_user(
    db: AsyncSession,
    username: str,
    password: str,
    email: Optional[str] = None,
    role: str = "user",
    is_demo: int = 0,
) -> dict:
    """注册用户，检查用户名/邮箱唯一性。返回用户 dict。"""
    if role not in {"admin", "user"}:
        raise ValueError("无效的用户角色")
    if is_demo not in {0, 1} or (is_demo and role != "user"):
        raise ValueError("演示账号必须是普通用户")
    email = email or None
    # 检查用户名
    result = await db.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": username},
    )
    if result.fetchone():
        raise ValueError("用户名已存在")

    if email:
        result = await db.execute(
            select(User.id).where(User.email == email)
        )
        if result.first():
            raise ValueError("邮箱已存在")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hashed = hash_password(password)

    db.add(User(
        id=user_id, username=username, email=email, password_hash=hashed,
        role=role, is_demo=is_demo, is_active=1, created_at=now, updated_at=now,
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ValueError("用户名或邮箱已存在") from None
    logger.info(f"用户注册成功: {username} (role={role})")

    return {
        "id": user_id,
        "username": username,
        "email": email,
        "role": role,
        "is_demo": is_demo,
        "is_active": 1,
        "created_at": now,
    }


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[dict]:
    """验证用户名密码，返回用户 dict 或 None"""
    result = await db.execute(
        text(
            "SELECT id, username, email, password_hash, role, is_demo, is_active, created_at "
            "FROM users WHERE username = :username"
        ),
        {"username": username},
    )
    row = result.fetchone()
    if not row:
        return None

    user = dict(row._mapping)
    if not verify_password(password, user["password_hash"]):
        return None

    if user.get("is_active", 1) != 1:
        return None

    return user


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    """验证 refresh token + session 有效性，返回新的 access token"""
    try:
        payload = verify_token(refresh_token)
    except ExpiredSignatureError:
        raise ValueError("Refresh token 已过期")
    except JWTError:
        raise ValueError("无效的 refresh token")

    if payload.get("type") != "refresh":
        raise ValueError("Token 类型错误")

    user_id = payload.get("sub")

    session_row = await db.scalar(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.refresh_token == refresh_token,
        )
    )

    if not session_row:
        raise ValueError("会话不存在")

    if session_row.is_revoked == 1:
        raise ValueError("会话已被吊销")
    expires_at = session_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("会话已过期")

    # 查用户信息来生成新 token
    result = await db.execute(
        text("SELECT id, username, role, is_active FROM users WHERE id = :id"),
        {"id": user_id},
    )
    user_row = result.fetchone()
    if not user_row:
        raise ValueError("用户不存在")

    user = dict(user_row._mapping)
    if user.get("is_active", 1) != 1:
        raise ValueError("用户已禁用")

    return create_access_token(user["id"], user["username"], user["role"])


async def revoke_session(db: AsyncSession, refresh_token: str) -> None:
    """吊销 session（设置 is_revoked=1）"""
    await db.execute(
        update(UserSession).where(UserSession.refresh_token == refresh_token).values(is_revoked=1)
    )
    await db.commit()


async def revoke_all_user_sessions(db: AsyncSession, user_id: str) -> None:
    """吊销用户所有 session"""
    await db.execute(
        update(UserSession).where(UserSession.user_id == user_id).values(is_revoked=1)
    )
    await db.commit()


# ==================== 日志与会话 ====================

async def log_login(
    db: AsyncSession,
    user_id: str,
    ip_address: str,
    user_agent: str,
    status: str,
) -> None:
    """记录登录日志"""
    await db.execute(
        text(
            "INSERT INTO login_logs (id, user_id, ip_address, user_agent, status, created_at) "
            "VALUES (:id, :user_id, :ip_address, :user_agent, :status, :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "ip_address": ip_address or "",
            "user_agent": (user_agent or "")[:500],
            "status": status,
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
        },
    )
    await db.commit()


async def create_session(
    db: AsyncSession,
    user_id: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    """创建会话记录"""
    if expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    db.add(UserSession(
        id=str(uuid.uuid4()), user_id=user_id, refresh_token=refresh_token,
        expires_at=expires_at, is_revoked=0,
    ))
    await db.commit()


# ==================== 初始化 ====================

async def create_initial_admin(db: AsyncSession) -> None:
    """检查是否存在管理员，不存在则创建默认管理员"""
    if not settings.DEFAULT_ADMIN_PASSWORD:
        logger.info("未配置初始管理员密码，跳过初始化")
        return
    result = await db.execute(
        text("SELECT id, role FROM users WHERE username = :username"),
        {"username": settings.DEFAULT_ADMIN_USERNAME},
    )
    existing = result.fetchone()
    if existing:
        if existing._mapping["role"] != "admin":
            raise ValueError("初始管理员用户名与普通用户冲突")
        logger.info("管理员账户已存在，跳过初始化")
        return

    await register_user(
        db,
        username=settings.DEFAULT_ADMIN_USERNAME,
        password=settings.DEFAULT_ADMIN_PASSWORD,
        role="admin",
    )
    logger.info("初始管理员已创建")
