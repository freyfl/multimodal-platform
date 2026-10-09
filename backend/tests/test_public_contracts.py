"""T1 tests intentionally import no business routers or real SDK clients."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import Settings, get_model_catalog
from app.errors import MissingConfigurationError, ServiceError, VectorSpaceMismatchError
from app.models.schemas import (
    MAX_CUSTOM_TAG_PROMPT_LENGTH, ImportStartRequest, ImportTaskDetail,
    ImportTaskResponse, PublicSystemConfig, SearchResultItem, TagSearchRequest,
    TagSystemResponse, UserSettingsResponse, UserSettingsUpdate,
)
from app.services.tag_service import DEFAULT_TAG_PROMPT
from app.vector_space import (
    ARK_EMBEDDING_MODEL, ARK_TAG_MODEL, IMAGE_CORPUS_INSTRUCTION,
    IMAGE_QUERY_INSTRUCTION, TEXT_QUERY_INSTRUCTION, VIDEO_CORPUS_INSTRUCTION,
    VectorSpace, cosine_to_similarity, validate_vector,
)


def test_empty_config_and_exact_defaults(empty_settings):
    assert empty_settings.ARK_TAG_MODEL == "doubao-seed-2-1-lite-260915"
    assert empty_settings.ARK_EMBEDDING_MODEL == "doubao-embedding-vision-251215"
    assert empty_settings.EMBEDDING_DIMENSION == 1024
    assert empty_settings.ARK_BASE_URL == "https://ark.cn-beijing.volces.com/api/v3"
    assert empty_settings.TEXT_SEARCH_MIN_SCORE == 0
    assert empty_settings.MILVUS_AUTH_ENABLED is False


@pytest.mark.parametrize("service", ["tos", "ark", "milvus", "mysql", "application"])
def test_missing_config_is_explicit_and_safe(empty_settings, service):
    with pytest.raises(MissingConfigurationError) as captured:
        empty_settings.require_config(service)
    error = captured.value
    assert error.service == service
    assert error.category == "not_configured"
    assert error.missing_fields
    assert error.retryable is False
    assert error.status_code == 503


def test_token_or_password_milvus_auth(empty_settings):
    empty_settings.MILVUS_URI = "https://milvus.invalid:19530"
    empty_settings.MILVUS_AUTH_ENABLED = True
    empty_settings.MILVUS_TOKEN = "test-token"
    empty_settings.require_config("milvus")
    empty_settings.MILVUS_TOKEN = ""
    empty_settings.MILVUS_USER = "test-user"
    empty_settings.MILVUS_PASSWORD = "test-password"
    empty_settings.require_config("milvus")


def test_local_milvus_can_explicitly_disable_auth(empty_settings):
    empty_settings.MILVUS_URI = "http://127.0.0.1:19530"
    empty_settings.MILVUS_AUTH_ENABLED = False
    empty_settings.require_config("milvus")


@pytest.mark.parametrize("field,value", [
    ("ARK_TAG_MODEL", "qwen-vl-plus"),
    ("ARK_EMBEDDING_MODEL", "qwen3-vl-embedding"),
    ("EMBEDDING_DIMENSION", 1536),
    ("EMBEDDING_CORPUS_INSTRUCTION_VERSION", "unknown-v2"),
    ("ARK_MAX_RETRIES", 100),
    ("TEXT_SEARCH_MIN_SCORE", -0.1),
])
def test_invalid_configuration_rejected(empty_settings, field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_dotenv_template_matches_configuration(empty_settings):
    template = Path(__file__).resolve().parents[1] / ".env.example"
    from dotenv import dotenv_values

    values = dotenv_values(template)
    infrastructure_only = {
        "INFRA_MYSQL_ROOT_PASSWORD",
        "INFRA_MINIO_ROOT_USER",
        "INFRA_MINIO_ROOT_PASSWORD",
    }
    assert not (set(values) - set(Settings.model_fields) - infrastructure_only)
    config = Settings(_env_file=template)
    assert config.vector_space == empty_settings.vector_space
    assert config.MYSQL_HOST == "127.0.0.1"
    assert config.MYSQL_SSL_ENABLED is False
    assert config.MILVUS_URI == "http://127.0.0.1:19530"
    assert config.MILVUS_AUTH_ENABLED is False
    assert config.MILVUS_SECURE is False
    for name in (
        "ARK_API_KEY", "TOS_ACCESS_KEY_SECRET", "MYSQL_PASSWORD", "MILVUS_TOKEN",
        "JWT_SECRET_KEY", *infrastructure_only,
    ):
        assert values[name] == ""


def test_secrets_not_in_repr_or_serialized_settings(empty_settings):
    empty_settings.ARK_API_KEY = "unique-test-secret"
    empty_settings.MYSQL_PASSWORD = "unique-test-secret"
    empty_settings.TOS_ACCESS_KEY_ID = "unique-test-secret"
    assert "unique-test-secret" not in repr(empty_settings)
    assert "unique-test-secret" not in empty_settings.model_dump_json()
    assert "unique-test-secret" not in json.dumps(get_model_catalog(empty_settings))


def test_mysql_password_roundtrip(empty_settings):
    password = "test:p@ss/with?#%+ space"
    empty_settings.MYSQL_USER = "test@user"
    empty_settings.MYSQL_PASSWORD = password
    empty_settings.MYSQL_HOST = "mysql.invalid"
    for url in (empty_settings.mysql_url, empty_settings.mysql_sync_url):
        assert url.password == password
        assert password not in str(url)
        assert make_url(url.render_as_string(hide_password=False)).password == password


@pytest.mark.parametrize("directory", [
    "tos://sample/", "tos://sample/prefix/", "tos://sample/\u4e2d\u6587 +%#/",
])
def test_import_new_fields_and_defaults(directory):
    request = ImportStartRequest(tos_directory=directory)
    assert request.tos_directory == directory
    assert request.embedding_model == ARK_EMBEDDING_MODEL
    assert request.embedding_dimension == 1024
    assert request.tag_model == ARK_TAG_MODEL
    assert request.tag_mode == "default"
    assert request.custom_tag_prompt is None


def test_import_custom_prompt_is_trimmed():
    request = ImportStartRequest(
        tos_directory="tos://sample/",
        tag_mode="custom",
        custom_tag_prompt="  classify road hazards  ",
    )
    assert request.custom_tag_prompt == "classify road hazards"


@pytest.mark.parametrize("prompt", [None, "", " \r\n\t "])
def test_enabled_custom_mode_requires_non_empty_prompt(prompt):
    with pytest.raises(ValidationError, match="非空"):
        ImportStartRequest(
            tos_directory="tos://sample/",
            tag_mode="custom",
            custom_tag_prompt=prompt,
        )


def test_enabled_custom_mode_rejects_oversized_prompt():
    with pytest.raises(ValidationError, match=str(MAX_CUSTOM_TAG_PROMPT_LENGTH)):
        ImportStartRequest(
            tos_directory="tos://sample/",
            tag_mode="custom",
            custom_tag_prompt="x" * (MAX_CUSTOM_TAG_PROMPT_LENGTH + 1),
        )


def test_default_mode_rejects_effective_custom_prompt():
    with pytest.raises(ValidationError, match="不接受"):
        ImportStartRequest(
            tos_directory="tos://sample/",
            custom_tag_prompt="custom rules",
        )


def test_disabled_tag_generation_ignores_custom_prompt_validation():
    request = ImportStartRequest(
        tos_directory="tos://sample/",
        generate_tags=False,
        tag_mode="custom",
        custom_tag_prompt="x" * (MAX_CUSTOM_TAG_PROMPT_LENGTH + 1),
    )
    assert request.custom_tag_prompt is None


@pytest.mark.parametrize("body", [
    {"oss_directory": "oss://sample/"},
    {"tos_directory": "oss://sample/"},
    {"tos_directory": "/local/directory"},
    {"tos_directory": "tos:///prefix/"},
    {"tos_directory": "tos://sample"},
    {"tos_directory": "tos://sample/", "embedding_model": "qwen3-vl-embedding"},
    {"tos_directory": "tos://sample/", "embedding_dimension": 768},
    {"tos_directory": "tos://sample/", "tag_model": "qwen-vl-plus"},
    {"tos_directory": "tos://sample/", "oss_directory": "oss://sample/"},
])
def test_old_or_invalid_import_contract_rejected(body):
    with pytest.raises(ValidationError):
        ImportStartRequest(**body)


def test_settings_blanks_preserve_stored_secrets():
    update = UserSettingsUpdate(
        tos_access_key_id="", tos_access_key_secret="  ", tos_security_token=None,
        ark_api_key="", tos_bucket_name="sample",
    )
    assert update.updates() == {"tos_bucket_name": "sample"}
    assert UserSettingsUpdate(ark_api_key="new-test-key").updates() == {"ark_api_key": "new-test-key"}


@pytest.mark.parametrize("body", [
    {"oss_bucket_name": "sample"},
    {"dashscope_api_key": "test"},
    {"embedding_model": "qwen3-vl-embedding"},
    {"embedding_dimension": 768},
])
def test_old_user_settings_rejected(body):
    with pytest.raises(ValidationError):
        UserSettingsUpdate(**body)


def test_response_contract_never_returns_credentials():
    response = UserSettingsResponse(
        id="settings-1", user_id="user-1", ark_api_key_masked="unique-test-key",
        tos_access_key_id_masked="test-id", tos_security_token_masked="test-token",
    ).model_dump()
    assert response["ark_api_key_masked"] == "****"
    assert response["tos_access_key_id_masked"] == "****"
    assert "unique-test-key" not in json.dumps(response)
    with pytest.raises(ValidationError):
        UserSettingsResponse(id="1", user_id="2", ark_api_key="test")


def test_media_and_task_contracts():
    assert "tos_directory" in ImportTaskResponse.model_fields
    assert "oss_directory" not in ImportTaskResponse.model_fields
    item = SearchResultItem(
        media_id="media-1", tos_url="tos://sample/file.png",
        preview_url="https://sample.invalid/file.png?signature=test",
        file_type="image", file_name="file.png", similarity=1,
    )
    assert item.preview_url.endswith("?signature=test")
    assert "oss_url" not in item.model_dump()
    task = ImportTaskDetail(
        task_id="task-1", tos_directory="tos://sample/", tag_mode="custom",
        status="pending", total_files=0, processed_files=0, failed_files=0,
        created_at="2026-09-18T00:00:00",
    ).model_dump()
    assert task["tag_mode"] == "custom"
    assert "custom_tag_prompt" not in task


def test_source_aware_tag_contracts_are_strict():
    request = TagSearchRequest(tags=[{
        "source": "custom", "category": "  hazard ", "name": " cone ",
    }])
    assert request.tags[0].model_dump() == {
        "source": "custom", "category": "hazard", "name": "cone",
    }
    with pytest.raises(ValidationError):
        TagSearchRequest(tags=[{"category": "road", "name": "交叉路口"}])
    with pytest.raises(ValidationError):
        TagSearchRequest(tags=[{
            "source": "default", "category": "road", "name": "交叉路口",
            "weight": 1,
        }])


def test_tag_system_is_grouped_by_source():
    response = TagSystemResponse(
        default=[{"source": "default", "category": "road", "name": "交叉路口"}],
        custom=[{"source": "custom", "category": "hazard", "name": "cone"}],
        default_prompt=DEFAULT_TAG_PROMPT,
    ).model_dump()
    assert set(response) == {"default", "custom", "default_prompt"}
    assert response["default_prompt"] == DEFAULT_TAG_PROMPT
    assert response["custom"][0]["source"] == "custom"
    with pytest.raises(ValidationError):
        TagSystemResponse(
            default=[{"source": "custom", "category": "road", "name": "wrong"}],
            default_prompt=DEFAULT_TAG_PROMPT,
        )


def test_public_model_catalog_shape(empty_settings):
    catalog = get_model_catalog(empty_settings)
    assert set(catalog) == {"embedding_models", "tag_models", "defaults", "vector_space"}
    assert list(catalog["embedding_models"]) == [ARK_EMBEDDING_MODEL]
    assert list(catalog["tag_models"]) == [ARK_TAG_MODEL]
    assert catalog["embedding_models"][ARK_EMBEDDING_MODEL]["dimensions"] == [1024]
    assert catalog["vector_space"] == empty_settings.vector_space.to_dict()
    public = PublicSystemConfig(
        appName=empty_settings.APP_NAME, version=empty_settings.APP_VERSION,
        model_catalog=catalog,
    )
    assert set(public.model_dump()) == {"apiPrefix", "appName", "version", "model_catalog"}


def test_vector_identity_includes_both_instruction_versions():
    space = VectorSpace()
    space.assert_compatible(space.to_dict())
    for key in space.to_dict():
        missing = space.to_dict()
        del missing[key]
        with pytest.raises(VectorSpaceMismatchError):
            space.assert_compatible(missing)
        different = {**space.to_dict(), key: "different"}
        with pytest.raises(VectorSpaceMismatchError):
            space.assert_compatible(different)
    with pytest.raises(VectorSpaceMismatchError):
        space.assert_compatible({**space.to_dict(), "dimension": 1024.0})


@pytest.mark.parametrize("vector", [
    [], [0.0] * 1024, [1.0] * 768, [float("nan")] * 1024,
    [float("inf")] * 1024, ["1"] * 1024, [True] * 1024, None,
    [10 ** 1000] * 1024,
])
def test_malformed_vectors_rejected(vector):
    with pytest.raises(ServiceError, match="finite"):
        validate_vector(vector)


def test_vector_validation_does_not_modify_valid_values():
    vector = [1.0] + [0.0] * 1023
    assert VectorSpace().validate_vector(vector) == vector


@pytest.mark.parametrize("raw,expected", [(-1, 0), (0, 0), (0.7, 0.7), (1, 1), (1.1, 1)])
def test_score_contract(raw, expected):
    assert cosine_to_similarity(raw) == expected


def test_instruction_bytes_match_spec():
    assert IMAGE_CORPUS_INSTRUCTION == "Instruction:Compress the image into one word.\nQuery:"
    assert VIDEO_CORPUS_INSTRUCTION == "Instruction:Compress the video into one word.\nQuery:"
    assert TEXT_QUERY_INSTRUCTION == "Target_modality: image/video.\nInstruction:\u6839\u636e\u63cf\u8ff0\u68c0\u7d22\u5339\u914d\u7684\u81ea\u52a8\u9a7e\u9a76\u9053\u8def\u573a\u666f\u56fe\u7247\u6216\u89c6\u9891\nQuery:"
    assert IMAGE_QUERY_INSTRUCTION == "Target_modality: image/video.\nInstruction:\u68c0\u7d22\u4e0e\u8f93\u5165\u56fe\u7247\u89c6\u89c9\u5185\u5bb9\u548c\u9053\u8def\u573a\u666f\u76f8\u4f3c\u7684\u56fe\u7247\u6216\u89c6\u9891\nQuery:"


def test_error_output_drops_untrusted_metadata():
    secret = "Authorization: Bearer test-secret https://example.invalid?signature=test-secret"
    error = ServiceError(secret, secret, request_id=secret, missing_fields=[secret])
    assert "test-secret" not in str(error)
    assert "test-secret" not in json.dumps(error.to_dict())
    error = ServiceError("ark", "rate_limit", request_id="req-123", retryable=True)
    assert error.to_dict()["request_id"] == "req-123"


def test_module_imports_are_lazy_and_do_not_read_dotenv(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    code = """
import socket
from unittest.mock import patch
def deny(*args, **kwargs):
    raise AssertionError("unexpected network or dotenv read")
socket.create_connection = deny
socket.getaddrinfo = deny
socket.socket.connect = deny
with patch("dotenv.main.DotEnv.dict", side_effect=deny):
    import app.config
    import app.models
    import app.models.schemas
    import app.services
    import app.services.contracts
    import sys
    assert "app.models.database" not in sys.modules
    assert "app.services.tos_service" not in sys.modules
    assert "app.services.embedding_service" not in sys.modules
    assert "app.services.milvus_service" not in sys.modules
    assert not any(key.startswith("OSS_") for key in app.config.Settings.model_fields)
"""
    env = {
        key: value for key, value in os.environ.items()
        if key not in Settings.model_fields and key != "APP_ENV_FILE"
    }
    env["PYTHONPATH"] = str(backend)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
