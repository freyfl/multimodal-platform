"""Authentication and user SQL regressions against in-memory SQLite."""

from datetime import datetime, timedelta, timezone
from importlib import import_module
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, settings
from app.models.database import get_session
from app.models.migrations import migrate
from app.models.models import User, UserSession
from app.models.schemas import PasswordChange, UserLogin, UserUpdate
from app.services import auth_service


@pytest_asyncio.fixture
async def db(monkeypatch):
    config = Settings(
        _env_file=None, JWT_SECRET_KEY="test-only-signing-key-with-at-least-32-characters",
        DEFAULT_ADMIN_PASSWORD="", ALLOW_REGISTRATION=True,
    )
    monkeypatch.setattr(auth_service, "settings", config)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", config.JWT_SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOW_REGISTRATION", True)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await migrate(engine)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_login_uuid_hash_roles_and_uniqueness(db):
    user = await auth_service.register_user(db, "tester", "password", "test@example.invalid", "admin")
    assert str(UUID(user["id"])) == user["id"]
    stored = await db.get(User, user["id"])
    assert stored.password_hash != "password"
    assert auth_service.verify_password("password", stored.password_hash)
    assert (await auth_service.authenticate_user(db, "tester", "password"))["role"] == "admin"
    assert await auth_service.authenticate_user(db, "tester", "wrong") is None
    with pytest.raises(ValueError, match="用户名"):
        await auth_service.register_user(db, "tester", "password")
    with pytest.raises(ValueError, match="邮箱"):
        await auth_service.register_user(db, "another", "password", "test@example.invalid")
    stored.is_active = 0
    await db.commit()
    assert await auth_service.authenticate_user(db, "tester", "password") is None


@pytest.mark.asyncio
async def test_registration_race_rolls_back_without_leaking_driver_message(monkeypatch):
    db = Mock()
    result = Mock()
    result.fetchone.return_value = None
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock(side_effect=IntegrityError("password hash SQL", {}, Exception("private-data")))
    db.rollback = AsyncMock()
    monkeypatch.setattr(auth_service, "hash_password", lambda value: "hashed")
    with pytest.raises(ValueError) as caught:
        await auth_service.register_user(db, "tester", "password")
    db.rollback.assert_awaited_once()
    assert "private-data" not in str(caught.value)


@pytest.mark.asyncio
async def test_refresh_and_logout_find_sessions_older_than_500_rows(db):
    user = await auth_service.register_user(db, "tester", "password")
    token = auth_service.create_refresh_token(user["id"])
    await auth_service.create_session(db, user["id"], token, datetime.now(timezone.utc) + timedelta(days=1))
    await db.execute(insert(UserSession), [
        {
            "id": f"new-session-{index}", "user_id": user["id"], "refresh_token": f"opaque-{index}",
            "expires_at": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=index + 1),
            "is_revoked": 0,
        }
        for index in range(501)
    ])
    await db.commit()
    access = await auth_service.refresh_access_token(db, token)
    assert auth_service.verify_token(access)["sub"] == user["id"]
    await auth_service.revoke_session(db, token)
    with pytest.raises(ValueError, match="吊销"):
        await auth_service.refresh_access_token(db, token)
    await auth_service.revoke_all_user_sessions(db, user["id"])
    assert await db.scalar(select(func.count()).select_from(UserSession).where(UserSession.is_revoked == 0)) == 0


@pytest.mark.asyncio
async def test_refresh_checks_database_expiry_and_disabled_user(db):
    user = await auth_service.register_user(db, "tester", "password")
    token = auth_service.create_refresh_token(user["id"])
    await auth_service.create_session(db, user["id"], token, datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(ValueError, match="过期"):
        await auth_service.refresh_access_token(db, token)
    row = await db.scalar(select(UserSession))
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    stored = await db.get(User, user["id"])
    stored.is_active = 0
    await db.commit()
    with pytest.raises(ValueError, match="禁用"):
        await auth_service.refresh_access_token(db, token)
    with pytest.raises(ValueError, match="类型"):
        await auth_service.refresh_access_token(db, auth_service.create_access_token(user["id"], "tester", "user"))


@pytest.mark.asyncio
async def test_user_pagination_counts_past_1000_and_escapes_like(db):
    user_router = import_module("app.api.user_router")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute(insert(User), [
        {
            "id": f"user-{index}", "username": f"user-{index}",
            "password_hash": "preserved-hash", "role": "user", "is_active": 1, "created_at": now,
        }
        for index in range(1005)
    ])
    db.add(User(username="literal_%name", password_hash="hash", role="admin", is_active=1))
    await db.commit()
    response = await user_router.list_users(
        page=51, page_size=20, role=None, is_active=None, keyword=None, admin={"id": "admin"}, db=db,
    )
    assert response.data["total"] == 1006
    assert len(response.data["items"]) == 6
    filtered = await user_router.list_users(
        page=1, page_size=20, role=None, is_active=None, keyword="_%", admin={"id": "admin"}, db=db,
    )
    assert filtered.data["total"] == 1


@pytest.mark.asyncio
async def test_active_sessions_exclude_expired_and_revoked(db):
    user_router = import_module("app.api.user_router")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add_all([
        UserSession(user_id="user", refresh_token="active", expires_at=now + timedelta(days=1)),
        UserSession(user_id="user", refresh_token="expired", expires_at=now - timedelta(days=1)),
        UserSession(user_id="user", refresh_token="revoked", expires_at=now + timedelta(days=1), is_revoked=1),
    ])
    await db.commit()
    result = await user_router.list_active_sessions(admin={"id": "admin"}, db=db)
    assert len(result.data) == 1
    assert "refresh_token" not in result.data[0]


@pytest.mark.asyncio
async def test_update_conflict_returns_409_and_transaction_remains_usable(db):
    user_router = import_module("app.api.user_router")
    first = await auth_service.register_user(db, "first", "password", "one@example.invalid")
    second = await auth_service.register_user(db, "second", "password", "two@example.invalid")
    with pytest.raises(HTTPException) as caught:
        await user_router.update_user(
            second["id"], UserUpdate(email=first["email"]), admin={"id": "admin"}, db=db,
        )
    assert caught.value.status_code == 409
    assert (await db.get(User, second["id"])).email == second["email"]


@pytest.mark.asyncio
async def test_password_change_revokes_tokens_in_same_commit(db):
    auth_router = import_module("app.api.auth_router")
    user = await auth_service.register_user(db, "tester", "old-password")
    token = auth_service.create_refresh_token(user["id"])
    await auth_service.create_session(db, user["id"], token, datetime.now(timezone.utc) + timedelta(days=1))
    await auth_router.change_password(PasswordChange(old_password="old-password", new_password="new-password"), user, db)
    assert await auth_service.authenticate_user(db, "tester", "old-password") is None
    assert await auth_service.authenticate_user(db, "tester", "new-password")
    with pytest.raises(ValueError, match="吊销"):
        await auth_service.refresh_access_token(db, token)


@pytest.mark.asyncio
async def test_demo_user_cannot_change_password(db):
    auth_router = import_module("app.api.auth_router")
    with pytest.raises(HTTPException) as caught:
        await auth_router.change_password(
            PasswordChange(
                old_password="old-password", new_password="new-password",
            ),
            {"id": "demo", "is_demo": 1},
            db,
        )
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_session_write_failure_does_not_return_login_success(db, monkeypatch):
    auth_router = import_module("app.api.auth_router")
    await auth_service.register_user(db, "tester", "password")
    monkeypatch.setattr(auth_service, "create_session", AsyncMock(
        side_effect=OperationalError("insert", {}, Exception("db unavailable"))
    ))
    request = Mock(headers={}, client=None)
    with pytest.raises(OperationalError):
        await auth_router.login(UserLogin(username="tester", password="password"), request, db)


@pytest.mark.asyncio
async def test_initial_admin_is_optional_and_conflicts_are_visible(db, monkeypatch):
    await auth_service.create_initial_admin(db)
    assert await db.scalar(select(func.count()).select_from(User)) == 0
    await auth_service.register_user(db, "admin", "password", role="user")
    monkeypatch.setattr(auth_service.settings, "DEFAULT_ADMIN_PASSWORD", "test-admin-password")
    with pytest.raises(ValueError, match="冲突"):
        await auth_service.create_initial_admin(db)


@pytest.mark.asyncio
async def test_auth_http_register_login_refresh_and_logout(db):
    auth_router = import_module("app.api.auth_router")
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api")

    async def session_override():
        yield db

    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        anonymous = await client.get("/api/auth/me")
        assert anonymous.status_code == 401
        assert anonymous.headers["www-authenticate"] == "Bearer"
        response = await client.post("/api/auth/register", json={
            "username": "tester", "password": "password", "email": "test@example.invalid", "role": "admin",
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["user"]["role"] == "user"
        assert "password_hash" not in data["user"]
        token = data["refresh_token"]
        headers = {"Authorization": f"Bearer {data['access_token']}"}
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
        assert (await client.post("/api/auth/refresh", json={"refresh_token": token})).status_code == 200
        assert (await client.post("/api/auth/logout", headers=headers, json={"refresh_token": token})).status_code == 200
        assert (await client.post("/api/auth/refresh", json={"refresh_token": token})).status_code == 401
        assert (await client.post("/api/auth/login", json={"username": "tester", "password": "password"})).status_code == 200
