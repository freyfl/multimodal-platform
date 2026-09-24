"""Offline settings CRUD against real SQLite SQL, with mocked cloud clients."""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.errors import ServiceError, VectorSpaceMismatchError
from app.models.database import Base
from app.models import models  # Register all tables without opening a connection.
from app.models.schemas import UserSettingsUpdate


@pytest.fixture
def api_modules():
    return SimpleNamespace(**{
        name: importlib.import_module(f"app.api.{name}")
        for name in ("deps", "settings_router", "system_router")
    })


class SQLiteSession:
    """Execute production text SQL on SQLite without an optional async driver."""

    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    async def execute(self, statement, parameters=None):
        self.statements.append(str(statement))
        return self.connection.execute(statement, parameters or {})

    async def commit(self):
        self.connection.commit()

    async def rollback(self):
        self.connection.rollback()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        yield SQLiteSession(connection)
    engine.dispose()


@pytest.fixture
def config(api_modules, empty_settings, monkeypatch):
    cfg = empty_settings.model_copy(update={
        "TOS_ACCESS_KEY_ID": "global-access-id",
        "TOS_ACCESS_KEY_SECRET": "global-secret",
        "TOS_SECURITY_TOKEN": "global-token",
        "TOS_BUCKET_NAME": "global-bucket",
        "TOS_ENDPOINT": "https://tos.invalid",
        "ARK_API_KEY": "global-ark-key",
    })
    monkeypatch.setattr(api_modules.deps, "settings", cfg)
    monkeypatch.setattr(api_modules.system_router, "settings", cfg)
    return cfg


@pytest.fixture
async def client(api_modules, db, config):
    app = FastAPI()
    app.include_router(api_modules.settings_router.router, prefix="/api")
    app.include_router(api_modules.system_router.router, prefix="/api")
    app.dependency_overrides[api_modules.deps.get_current_user] = lambda: {
        "id": "user-a", "role": "user", "is_demo": 0,
    }
    app.dependency_overrides[api_modules.settings_router.get_session] = lambda: db

    @app.exception_handler(ServiceError)
    async def service_error_handler(request, error):
        return JSONResponse(status_code=error.status_code, content={
            "code": error.status_code, "message": error.message, "data": error.to_dict(),
        })

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as http:
        yield http


async def test_defaults_and_crud_preserve_secrets_and_user_isolation(client, db, api_modules):
    result = (await client.get("/api/settings/me")).json()["data"]
    assert result["id"] == ""
    assert result["tos_bucket_name"] is None
    assert result["embedding_dimension"] == 1024
    assert result["ark_api_key_masked"] is None
    assert "global-secret" not in json.dumps(result)

    values = {
        "tos_access_key_id": "custom-access", "tos_access_key_secret": "custom-secret",
        "tos_security_token": "custom-token", "ark_api_key": "custom-ark",
        "tos_bucket_name": "custom-bucket",
    }
    created = await client.put("/api/settings/me", json=values)
    assert created.status_code == 200
    assert created.json()["data"]["id"]
    for key in api_modules.deps.SECRET_SETTING_FIELDS:
        assert key not in created.json()["data"]
        assert created.json()["data"][f"{key}_masked"] == "****"
        assert values[key] not in created.text

    await client.put("/api/settings/me", json={
        "tos_access_key_id": "", "tos_access_key_secret": "  ",
        "tos_security_token": "", "ark_api_key": "",
        "tos_bucket_name": "updated-bucket",
    })
    row = await api_modules.deps.get_user_settings_row(db, "user-a")
    for key in api_modules.deps.SECRET_SETTING_FIELDS:
        assert row[key] == values[key]
    effective = await api_modules.deps.get_user_settings({"id": "user-a"}, db)
    assert effective["tos_bucket_name"] == "updated-bucket"
    assert effective["tos_endpoint"] is None
    assert effective["ark_api_key"] == "custom-ark"
    assert effective["is_custom"] is True

    await api_modules.settings_router.update_my_settings(
        UserSettingsUpdate(tos_bucket_name="other-bucket"), {"id": "user-b"}, db,
    )
    deleted = await client.delete("/api/settings/me")
    assert deleted.json()["data"]["tos_bucket_name"] is None
    assert await api_modules.deps.get_user_settings_row(db, "user-a") is None
    assert (await api_modules.deps.get_user_settings_row(db, "user-b"))["tos_bucket_name"] == "other-bucket"
    assert (await client.delete("/api/settings/me")).status_code == 200


async def test_empty_save_does_not_create_custom_row(client, db, api_modules):
    response = await client.put("/api/settings/me", json={"ark_api_key": " "})
    assert response.status_code == 200
    assert await api_modules.deps.get_user_settings_row(db, "user-a") is None


async def test_effective_settings_layer_drafts_and_allow_clearing_non_secrets(
    api_modules, config,
):
    effective = api_modules.deps.effective_user_settings(
        {"ark_api_key": "saved-key", "tos_custom_domain": "https://cdn.invalid"},
        {"ark_api_key": " ", "tos_custom_domain": ""},
    )
    assert effective["ark_api_key"] == "saved-key"
    assert effective["tos_custom_domain"] == ""
    assert effective["tos_endpoint"] is None


@pytest.mark.parametrize("body", [
    {"embedding_model": "unsupported"}, {"embedding_dimension": 768},
    {"tag_model": "unsupported"}, {"oss_bucket_name": "old"},
])
async def test_invalid_settings_rejected_without_persistence(client, db, api_modules, body):
    assert (await client.put("/api/settings/me", json=body)).status_code == 422
    assert await api_modules.deps.get_user_settings_row(db, "user-a") is None


@pytest.mark.parametrize("field,value", [
    ("embedding_model", "old-model"), ("embedding_dimension", 768),
    ("embedding_dimension", True),
])
def test_stored_model_mismatch_rejected(api_modules, config, field, value):
    with pytest.raises(VectorSpaceMismatchError):
        api_modules.deps.effective_user_settings({field: value})


async def test_sql_failures_are_safe_and_roll_back(api_modules):
    db = AsyncMock()
    db.execute.side_effect = OperationalError("secret SQL", {}, Exception("password=secret"))
    with pytest.raises(ServiceError) as captured:
        await api_modules.deps.get_user_settings_row(db, "user-a")
    assert captured.value.service == "mysql"
    assert "secret" not in str(captured.value)
    with pytest.raises(ServiceError):
        await api_modules.settings_router.delete_my_settings({"id": "user-a"}, db)
    db.rollback.assert_awaited_once()


@pytest.mark.parametrize("existing", [False, True])
async def test_write_failure_rolls_back_and_redacts(api_modules, config, monkeypatch, existing):
    db = AsyncMock()
    db.execute.side_effect = OperationalError("secret SQL", {}, Exception("secret-key"))
    monkeypatch.setattr(api_modules.settings_router, "get_user_settings_row", AsyncMock(
        return_value={"id": "setting-a", "user_id": "user-a"} if existing else None,
    ))
    with pytest.raises(ServiceError) as captured:
        await api_modules.settings_router.update_my_settings(
            UserSettingsUpdate(ark_api_key="secret-key"), {"id": "user-a"}, db,
        )
    assert captured.value.service == "mysql"
    assert "secret" not in str(captured.value)
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("failure", [None, ServiceError("tos", "permission"), RuntimeError("secret")])
async def test_tos_probe_uses_effective_settings_and_always_closes(
    client, api_modules, monkeypatch, failure,
):
    service = SimpleNamespace(
        check_connection=AsyncMock(return_value={"status": "ready"}, side_effect=failure),
        aclose=AsyncMock(),
    )
    factory = Mock(return_value=service)
    monkeypatch.setattr(api_modules.settings_router, "TOSService", factory)
    await client.put("/api/settings/me", json={
        "ark_api_key": "saved-key", "tos_bucket_name": "saved-bucket",
        "tos_access_key_secret": "saved-secret",
    })
    response = await client.post("/api/settings/me/test-tos", json={"tos_bucket_name": "draft-bucket"})
    data = response.json()["data"]
    assert data["success"] is (failure is None)
    assert "secret" not in response.text
    assert factory.call_args.kwargs["bucket_name"] == "draft-bucket"
    assert factory.call_args.kwargs["access_key_secret"] == "saved-secret"
    service.aclose.assert_awaited_once()


@pytest.mark.parametrize("failed", [None, "embedding", "tag", "both"])
async def test_ark_checks_both_models_with_effective_key(client, api_modules, monkeypatch, failed):
    services = {}
    for name in ("embedding", "tag"):
        service = SimpleNamespace(check_connection=AsyncMock(
            return_value={"status": "ok", "untrusted": "must-not-echo"},
            side_effect=ServiceError("ark", "permission", request_id="req-123")
            if failed in (name, "both") else None,
        ))
        services[name] = service
        monkeypatch.setattr(api_modules.settings_router, f"{name}_service", service)
    await client.put("/api/settings/me", json={"ark_api_key": "saved-key"})
    response = await client.post("/api/settings/me/test-ark", json={"ark_api_key": ""})
    data = response.json()["data"]
    assert data["success"] is (failed is None)
    assert (response.json()["code"] == 200) is (failed is None)
    for name, service in services.items():
        service.check_connection.assert_awaited_once_with(api_key="saved-key")
        assert data[name]["success"] is (failed not in (name, "both"))
        assert "error" in data[name]
    assert "saved-key" not in response.text
    assert "must-not-echo" not in response.text


async def test_missing_ark_config_reports_both_models(client, api_modules, config, monkeypatch):
    config.ARK_API_KEY = ""
    from app.errors import MissingConfigurationError

    for name in ("embedding", "tag"):
        monkeypatch.setattr(api_modules.settings_router, f"{name}_service", SimpleNamespace(
            check_connection=AsyncMock(side_effect=MissingConfigurationError("ark", ["ARK_API_KEY"])),
        ))
    data = (await client.post("/api/settings/me/test-ark")).json()["data"]
    assert data["success"] is False
    for name in ("embedding", "tag"):
        assert data[name]["error"]["category"] == "not_configured"


async def test_ark_probe_rejects_malformed_model_results(client, api_modules, monkeypatch):
    monkeypatch.setattr(api_modules.settings_router, "embedding_service", SimpleNamespace(
        check_connection=AsyncMock(return_value={"status": "unexpected", "secret": "hidden"}),
    ))
    monkeypatch.setattr(api_modules.settings_router, "tag_service", SimpleNamespace(
        check_connection=AsyncMock(return_value=None),
    ))
    response = await client.post("/api/settings/me/test-ark")
    assert response.json()["code"] == 503
    assert response.json()["data"]["success"] is False
    assert response.json()["data"]["embedding"]["error"]["category"] == "unavailable"
    assert response.json()["data"]["tag"]["error"]["category"] == "invalid_response"
    assert "hidden" not in response.text


async def test_legacy_probe_routes_removed(client):
    for route in ("test-oss", "test-apikey"):
        assert (await client.post(f"/api/settings/me/{route}")).status_code == 404


@pytest.mark.parametrize("operation", ["update", "delete", "tos", "ark"])
async def test_demo_user_cannot_manage_own_settings(
    api_modules, db, operation,
):
    demo = {"id": "demo-user", "role": "user", "is_demo": 1}
    with pytest.raises(HTTPException) as captured:
        if operation == "update":
            await api_modules.settings_router.update_my_settings(
                UserSettingsUpdate(ark_api_key="forbidden"), demo, db,
            )
        elif operation == "delete":
            await api_modules.settings_router.delete_my_settings(demo, db)
        elif operation == "tos":
            await api_modules.settings_router.test_tos_connection(None, demo, db)
        else:
            await api_modules.settings_router.test_ark_connection(None, demo, db)
    assert captured.value.status_code == 403
    assert await api_modules.deps.get_user_settings_row(db, "demo-user") is None


async def test_admin_can_configure_demo_user(api_modules, db):
    await db.execute(text(
        "INSERT INTO users "
        "(id, username, password_hash, role, is_demo, is_active) "
        "VALUES ('demo-user', 'demo', 'hash', 'user', 1, 1)"
    ))
    response = await api_modules.settings_router.update_user_settings_as_admin(
        "demo-user",
        UserSettingsUpdate(
            ark_api_key="admin-managed-key",
            tos_bucket_name="demo-bucket",
        ),
        {"id": "admin", "role": "admin"},
        db,
    )
    assert response.data["ark_api_key_masked"] == "****"
    saved = await api_modules.deps.get_user_settings_row(db, "demo-user")
    assert saved["ark_api_key"] == "admin-managed-key"
    assert saved["tos_bucket_name"] == "demo-bucket"


@pytest.mark.parametrize("active", [0, 1])
async def test_current_user_enforces_active_state(api_modules, db, monkeypatch, active):
    await db.execute(text(
        "INSERT INTO users (id, username, password_hash, role, is_active) "
        "VALUES ('user-a', 'alice', 'hash', 'user', :active)"
    ), {"active": active})
    monkeypatch.setattr(api_modules.deps, "verify_token", lambda token: {"type": "access", "sub": "user-a"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-only")
    if active:
        user = await api_modules.deps.get_current_user(credentials, db)
        assert user["username"] == "alice"
        assert "password_hash" not in user
    else:
        with pytest.raises(HTTPException) as captured:
            await api_modules.deps.get_current_user(credentials, db)
        assert captured.value.status_code == 403


async def test_current_user_missing_application_config_is_not_invalid_token(api_modules, monkeypatch):
    from app.errors import MissingConfigurationError

    monkeypatch.setattr(api_modules.deps, "verify_token", Mock(
        side_effect=MissingConfigurationError("application", ["JWT_SECRET_KEY"]),
    ))
    with pytest.raises(MissingConfigurationError):
        await api_modules.deps.get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-only"), AsyncMock(),
        )


@pytest.mark.parametrize("saved", [False, True])
async def test_missing_user_credentials_never_probe_deployment(
    client, api_modules, config, monkeypatch, saved,
):
    from app.services.ark_client import ArkClient
    from app.services.embedding_service import EmbeddingService
    from app.services.tag_service import TagService
    from app.services import tos_service as tos_module

    # Real adapters with complete deployment credentials, but no user's key.
    monkeypatch.setattr(tos_module, "settings", config.model_copy(update={
        "TOS_REGION": "cn-beijing",
    }))
    handler = Mock(side_effect=AssertionError("Must not call deployment credentials"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        ark = ArkClient(config=config, http_client=http)
        monkeypatch.setattr(api_modules.settings_router, "embedding_service", EmbeddingService(client=ark))
        monkeypatch.setattr(api_modules.settings_router, "tag_service", TagService(client=ark))
        if saved:
            await client.put("/api/settings/me", json={"tos_bucket_name": "user-bucket"})
        ark_response = await client.post("/api/settings/me/test-ark")
        tos_response = await client.post("/api/settings/me/test-tos")
    assert ark_response.json()["data"]["success"] is False
    for name in ("embedding", "tag"):
        assert ark_response.json()["data"][name]["error"]["category"] == "not_configured"
    assert tos_response.json()["data"]["error"]["category"] == "not_configured"
    assert "TOS_ACCESS_KEY_ID" in tos_response.json()["data"]["error"]["missing_fields"]
    handler.assert_not_called()
