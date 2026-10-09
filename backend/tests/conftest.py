"""Offline-only tests: no dotenv loading, DNS or outbound socket connections."""

import os
import socket
from unittest.mock import AsyncMock, Mock

import httpx
import pytest


# This runs before test-module imports; no test may use the developer's .env.
os.environ.pop("APP_ENV_FILE", None)


def _deny_network(*args, **kwargs):
    raise AssertionError("Real network access is disabled in backend tests")


# Block even collection-time I/O; local socketpair used by asyncio still works.
socket.create_connection = _deny_network
socket.getaddrinfo = _deny_network
socket.socket.connect = _deny_network
socket.socket.connect_ex = _deny_network


@pytest.fixture
def empty_settings(monkeypatch):
    from app.config import Settings

    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None)


@pytest.fixture
def mock_tos_client():
    """Synchronous SDK stub suitable for injection into TOSService."""
    return Mock(spec=[
        "list_objects_type2", "head_object", "get_object", "put_object",
        "put_object_from_file", "get_object_to_file", "delete_object",
        "pre_signed_url", "close",
    ])


@pytest.fixture
def mock_milvus_client():
    """Synchronous SDK stub, never constructs a real client."""
    return Mock(spec=[
        "has_collection", "create_collection", "describe_collection",
        "create_schema", "prepare_index_params", "create_index",
        "load_collection", "upsert", "search", "delete", "query",
        "get_collection_stats", "alter_collection_properties", "close",
    ])


@pytest.fixture
def mock_ark_transport():
    """Tests set handler.return_value to an httpx.Response."""
    handler = Mock(return_value=httpx.Response(
        503, json={"error": {"code": "offline_test", "message": "mock only"}}
    ))
    return handler, httpx.MockTransport(handler)


@pytest.fixture
def mock_cloud_services():
    from app.services.contracts import (
        EmbeddingContract, MilvusContract, TagContract, TOSContract,
    )

    return {
        "tos": AsyncMock(spec=TOSContract),
        "embedding": AsyncMock(spec=EmbeddingContract),
        "tag": AsyncMock(spec=TagContract),
        "milvus": AsyncMock(spec=MilvusContract),
    }
