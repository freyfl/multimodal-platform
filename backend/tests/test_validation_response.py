"""Exercise the actual app handler without lifespan or external services."""

import httpx
import pytest

from app.api.deps import get_current_user, get_user_settings
from app.main import app
from app.models.database import get_session


@pytest.mark.parametrize("payload", [
    {"tag_mode": "custom", "custom_tag_prompt": "  "},
    {"tag_mode": "custom", "custom_tag_prompt": "private-prompt" * 1000},
    {"tag_mode": "default", "custom_tag_prompt": "private-prompt"},
    {"tag_mode": "custom", "custom_tag_prompt": "private-prompt", "unknown": "private-key"},
])
async def test_invalid_import_returns_safe_422(monkeypatch, payload):
    monkeypatch.setattr(app, "dependency_overrides", {
        get_current_user: lambda: {"id": "user-1"},
        get_user_settings: lambda: {},
        get_session: lambda: None,
    })
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/import/start", json={
            "tos_directory": "tos://sample/",
            "generate_tags": True,
            **payload,
        })
    assert response.status_code == 422
    assert response.json()["code"] == 422
    for error in response.json()["data"]["errors"]:
        assert set(error) == {"type", "loc", "msg"}
    assert "private-prompt" not in response.text
    assert "private-key" not in response.text
