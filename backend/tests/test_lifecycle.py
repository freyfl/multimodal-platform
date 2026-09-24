"""Application lifecycle and import-safety regressions."""

import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import main
from app.utils.logger import CustomFormatter


def test_main_registers_tos_and_no_oss_routes():
    paths = set(main.app.openapi()["paths"])
    assert any(path.startswith("/api/tos/") for path in paths)
    assert not any("/oss" in path.lower() for path in paths)


async def test_lifespan_recovers_before_serving_and_closes_every_resource(monkeypatch):
    calls = []

    def operation(name, failure=False):
        async def run(*args, **kwargs):
            calls.append(name)
            if failure:
                raise RuntimeError("private credential")
        return AsyncMock(side_effect=run)

    monkeypatch.setattr(main, "prepare_import_tasks", lambda: calls.append("prepare"))
    monkeypatch.setattr(main, "init_db", operation("init"))
    monkeypatch.setattr(main, "recover_interrupted_imports", operation("recover"))
    monkeypatch.setattr(main, "annotation_job_service", SimpleNamespace(
        prepare=lambda: calls.append("annotation-prepare"),
        recover=operation("annotation-recover"),
        cleanup_temporary=operation("annotation-cleanup"),
        shutdown=operation("annotations"),
    ))
    monkeypatch.setattr(main, "create_initial_admin", operation("admin"))
    monkeypatch.setattr(main, "shutdown_import_tasks", operation("imports"))
    monkeypatch.setattr(main, "close_tos_services", operation("tos", failure=True))
    monkeypatch.setattr(main, "ark_client", SimpleNamespace(aclose=operation("ark")))
    monkeypatch.setattr(main, "milvus_service", SimpleNamespace(aclose=operation("milvus")))
    monkeypatch.setattr(main, "close_db", operation("database"))

    session = AsyncMock()
    session.__aenter__.return_value = SimpleNamespace()
    session.__aexit__.return_value = None
    monkeypatch.setattr(main, "async_session_maker", lambda: session)

    async with main.lifespan(main.app):
        assert calls == [
            "prepare", "annotation-prepare", "init", "recover",
            "annotation-recover", "annotation-cleanup", "admin",
        ]
        calls.append("served")

    assert calls == [
        "prepare", "annotation-prepare", "init", "recover",
        "annotation-recover", "annotation-cleanup", "admin", "served",
        "imports", "annotations", "tos", "ark", "milvus", "database",
    ]


async def test_startup_failure_still_closes_cloud_clients_and_database(monkeypatch):
    calls = []

    async def fail_init():
        calls.append("init")
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "prepare_import_tasks", lambda: calls.append("prepare"))
    monkeypatch.setattr(main, "init_db", fail_init)
    monkeypatch.setattr(main, "close_tos_services", AsyncMock(side_effect=lambda: calls.append("tos")))
    monkeypatch.setattr(
        main, "ark_client",
        SimpleNamespace(aclose=AsyncMock(side_effect=lambda: calls.append("ark"))),
    )
    monkeypatch.setattr(
        main, "milvus_service",
        SimpleNamespace(aclose=AsyncMock(side_effect=lambda: calls.append("milvus"))),
    )
    monkeypatch.setattr(main, "close_db", AsyncMock(side_effect=lambda: calls.append("database")))

    try:
        async with main.lifespan(main.app):
            raise AssertionError("unreachable")
    except RuntimeError:
        pass
    assert calls == ["prepare", "init", "tos", "ark", "milvus", "database"]


def test_logger_import_has_no_filesystem_or_dotenv_side_effect(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    code = """
import pathlib
from unittest.mock import patch
with patch("dotenv.main.DotEnv.dict", side_effect=AssertionError("dotenv read")):
    import app.utils.logger
assert not pathlib.Path("logs").exists()
"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(backend),
        "APP_ENV_FILE": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_logger_redacts_signed_urls_and_credentials():
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1,
        "Authorization: Bearer %s url=%s password=%s", (
            "private-token",
            "https://bucket.invalid/file?X-Tos-Signature=private-signature",
            "private-password",
        ), None,
    )
    text = CustomFormatter("%(levelname)s %(message)s").format(record)
    assert "private-" not in text
    assert "https://bucket.invalid/file?<redacted>" in text
