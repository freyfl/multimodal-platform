"""
用户管理路由模块
全部需要 admin 角色
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.models import User, UserSession
from app.models.schemas import (
    ApiResponse, UserCreate, UserResponse, UserUpdate, PaginatedUsers,
)
from app.services import auth_service
from app.api.deps import require_admin

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("/sessions/active", response_model=ApiResponse)
async def list_active_sessions(
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """查看所有活跃会话"""
    result = await db.execute(
        select(
            UserSession.id, UserSession.user_id, UserSession.expires_at,
            UserSession.created_at, UserSession.is_revoked,
        ).where(
            UserSession.is_revoked == 0,
            UserSession.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
        ).order_by(UserSession.created_at.desc()).limit(100)
    )
    rows = result.fetchall()
    items = [dict(r._mapping) for r in rows]
    # 序列化 datetime
    for item in items:
        for k in ("expires_at", "created_at"):
            if isinstance(item.get(k), datetime):
                item[k] = item[k].isoformat()
    return ApiResponse(data=items)


@router.get("/", response_model=ApiResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str = Query(None),
    is_active: int = Query(None),
    keyword: str = Query(None),
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """用户列表（分页）"""
    filters = []
    if role:
        filters.append(User.role == role)
    if is_active is not None:
        filters.append(User.is_active == is_active)
    if keyword:
        filters.append(or_(
            User.username.icontains(keyword, autoescape=True),
            User.email.icontains(keyword, autoescape=True),
        ))
    total = await db.scalar(select(func.count()).select_from(User).where(*filters))
    offset = (page - 1) * page_size
    result = await db.execute(
        select(
            User.id, User.username, User.email, User.role, User.is_demo,
            User.is_active, User.created_at,
        )
        .where(*filters).order_by(User.created_at.desc(), User.id)
        .offset(offset).limit(page_size)
    )
    page_items = result.mappings().all()
    items = [
        UserResponse(
            id=m["id"],
            username=m["username"],
            email=m.get("email"),
            role=m["role"],
            is_demo=m.get("is_demo", 0),
            is_active=m.get("is_active", 1),
            created_at=m.get("created_at"),
        )
        for m in page_items
    ]

    return ApiResponse(data=PaginatedUsers(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    ).model_dump())


@router.post("/", response_model=ApiResponse)
async def create_user(
    body: UserCreate,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """创建用户（管理员可指定角色）"""
    try:
        user = await auth_service.register_user(
            db,
            username=body.username,
            password=body.password,
            email=body.email,
            role=body.role,
            is_demo=body.is_demo,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return ApiResponse(
        message="用户创建成功",
        data=UserResponse(**{
            k: user[k] for k in (
                "id", "username", "email", "role", "is_demo",
                "is_active", "created_at",
            )
        }).model_dump(),
    )


@router.get("/{user_id}", response_model=ApiResponse)
async def get_user(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """用户详情"""
    result = await db.execute(
        text(
            "SELECT id, username, email, role, is_demo, is_active, created_at "
            "FROM users WHERE id = :id"
        ),
        {"id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    u = dict(row._mapping)
    return ApiResponse(data=UserResponse(**u).model_dump())


@router.put("/{user_id}", response_model=ApiResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """更新用户"""
    if body.role is not None and body.role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="无效的用户角色")
    if body.is_active is not None and body.is_active not in {0, 1}:
        raise HTTPException(status_code=400, detail="无效的用户状态")
    if body.is_demo is not None and body.is_demo not in {0, 1}:
        raise HTTPException(status_code=400, detail="无效的演示账号状态")
    if body.email is not None and len(body.email) > 100:
        raise HTTPException(status_code=400, detail="邮箱长度不能超过100个字符")
    # 不可更改自己的 admin 角色
    if user_id == admin["id"] and body.role and body.role != "admin":
        raise HTTPException(status_code=400, detail="不可更改自己的管理员角色")
    if user_id == admin["id"] and body.is_active == 0:
        raise HTTPException(status_code=400, detail="不可禁用自己")

    # 检查用户存在
    result = await db.execute(
        text("SELECT id, role, is_demo FROM users WHERE id = :id"), {"id": user_id}
    )
    existing = result.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="用户不存在")
    existing = dict(existing._mapping)
    next_role = body.role if body.role is not None else existing["role"]
    next_is_demo = body.is_demo if body.is_demo is not None else existing["is_demo"]
    if next_is_demo == 1 and next_role != "user":
        raise HTTPException(status_code=400, detail="演示账号必须是普通用户")
    if user_id == admin["id"] and body.is_demo == 1:
        raise HTTPException(status_code=400, detail="不可将自己设为演示账号")

    # 构建 SET 子句
    sets = []
    params: dict = {"id": user_id}
    if body.email is not None:
        sets.append("email = :email")
        params["email"] = body.email or None
    if body.role is not None:
        sets.append("role = :role")
        params["role"] = body.role
    if body.is_demo is not None:
        sets.append("is_demo = :is_demo")
        params["is_demo"] = body.is_demo
    if body.is_active is not None:
        sets.append("is_active = :is_active")
        params["is_active"] = body.is_active

    if not sets:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    sets.append("updated_at = :now")
    params["now"] = datetime.now(timezone.utc).replace(tzinfo=None)

    sql = f"UPDATE users SET {', '.join(sets)} WHERE id = :id"
    try:
        await db.execute(text(sql), params)
        if body.is_active == 0 or body.role is not None:
            await auth_service.revoke_all_user_sessions(db, user_id)
        else:
            await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="邮箱已存在") from None

    return ApiResponse(message="用户更新成功")


@router.delete("/{user_id}", response_model=ApiResponse)
async def disable_user(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """禁用用户（is_active=0，不物理删除）"""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不可禁用自己")

    result = await db.execute(
        text("SELECT id FROM users WHERE id = :id"), {"id": user_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.execute(
        text("UPDATE users SET is_active = 0, updated_at = :now WHERE id = :id"),
        {"id": user_id, "now": datetime.now(timezone.utc).replace(tzinfo=None)},
    )

    # Disabling the account and revoking refresh tokens are one transaction.
    await auth_service.revoke_all_user_sessions(db, user_id)

    return ApiResponse(message="用户已禁用")


@router.get("/{user_id}/login-logs", response_model=ApiResponse)
async def get_user_login_logs(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """查看用户登录日志"""
    offset = (page - 1) * page_size

    # 总数
    result = await db.execute(
        text("SELECT COUNT(*) AS cnt FROM login_logs WHERE user_id = :uid"),
        {"uid": user_id},
    )
    row = result.fetchone()
    total = dict(row._mapping)["cnt"] if row else 0

    # 数据
    result = await db.execute(
        text(
            "SELECT id, user_id, ip_address, user_agent, status, created_at "
            "FROM login_logs WHERE user_id = :uid "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        {"uid": user_id, "limit": page_size, "offset": offset},
    )
    rows = result.fetchall()
    items = []
    for r in rows:
        item = dict(r._mapping)
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat()
        items.append(item)

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })
