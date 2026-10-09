"""Offline tests against official SDK schemas, signatures and response shapes."""

import asyncio
import copy
import importlib
import inspect
import json
import threading
from unittest.mock import create_autospec, patch

import grpc
import pytest
from pymilvus import CollectionSchema, DataType, MilvusClient
from pymilvus.client.search_result import SearchResult
from pymilvus.exceptions import ErrorCode, MilvusException, ParamError
from pymilvus.grpc_gen import schema_pb2

from app.errors import MissingConfigurationError, ServiceError, VectorSpaceMismatchError
from app.services.contracts import MilvusContract
from app.services.milvus_service import MilvusService


def record(media_id="media-1", **changes):
    return {
        "media_id": media_id, "user_id": "user-1",
        "tos_url": "tos://sample/image.png",
        "file_type": "image", "embedding": [1.0] + [0.0] * 1023,
        **changes,
    }


def collection_config(config):
    return {
        "collection_name": config.MILVUS_COLLECTION,
        "description": json.dumps(config.vector_space.to_dict()),
        "auto_id": False, "enable_dynamic_field": False, "consistency_level": 0,
        "fields": [
            {
                "name": name, "type": DataType.VARCHAR,
                "is_primary": name == "media_id", "params": {"max_length": length},
            }
            for name, length in MilvusService.STRING_LENGTHS.items()
        ] + [{
            "name": "embedding", "type": DataType.FLOAT_VECTOR, "params": {"dim": 1024},
        }],
    }


@pytest.fixture
def sdk(empty_settings):
    client = create_autospec(MilvusClient, instance=True)
    client.has_collection.return_value = True
    client.describe_collection.return_value = collection_config(empty_settings)
    client.list_indexes.return_value = [MilvusService.INDEX_NAME]
    client.describe_index.return_value = {
        "index_name": MilvusService.INDEX_NAME, "field_name": "embedding",
        "index_type": "HNSW", "metric_type": "COSINE",
        "M": "16", "efConstruction": "200",
    }
    rows = {}

    def upsert(collection_name, data, timeout):
        for row in data:
            rows[row["media_id"]] = copy.deepcopy(row)
        return {"upsert_count": len(data), "ids": [row["media_id"] for row in data]}

    def delete(collection_name, ids, timeout):
        for media_id in ids:
            rows.pop(media_id, None)
        return {}

    def query(collection_name, filter, output_fields, timeout, **kwargs):
        assert filter in ("", 'user_id == "user-1"')
        assert output_fields == ["count(*)"]
        assert kwargs["consistency_level"] == "Strong"
        count = len(rows) if not filter else sum(
            row["user_id"] == "user-1" for row in rows.values()
        )
        return [{"count(*)": count}]

    client.upsert.side_effect = upsert
    client.delete.side_effect = delete
    client.query.side_effect = query
    client.search.return_value = [[]]
    return client, rows


@pytest.fixture
async def service(empty_settings, sdk):
    instance = MilvusService(empty_settings, client=sdk[0])
    yield instance
    await instance.aclose()


def test_contract_names_and_defaults():
    for name, method in vars(MilvusContract).items():
        if inspect.iscoroutinefunction(method):
            implementation = getattr(MilvusService, name)
            assert inspect.iscoroutinefunction(implementation)
            expected = inspect.signature(method).parameters
            actual = inspect.signature(implementation).parameters
            assert list(actual) == list(expected)
            for parameter in expected:
                assert actual[parameter].default == expected[parameter].default


def test_module_and_constructor_are_lazy(empty_settings):
    with patch("dotenv.main.DotEnv.dict", side_effect=AssertionError("dotenv read")):
        with patch("pymilvus.MilvusClient.__init__", side_effect=AssertionError("connected")):
            module = importlib.import_module("app.services.milvus_service")
            instance = module.MilvusService(empty_settings)
            assert instance._client is None
            assert instance._executor is None
            assert module.milvus_service._client is None


async def test_missing_configuration_is_not_an_empty_database(empty_settings):
    instance = MilvusService(empty_settings)
    try:
        with pytest.raises(MissingConfigurationError) as raised:
            await instance.get_vector_count()
        assert raised.value.service == "milvus"
        assert "MILVUS_URI" in raised.value.missing_fields
    finally:
        await instance.aclose()


@pytest.mark.parametrize("token", [True, False])
async def test_connection_options_and_worker_thread(empty_settings, sdk, token):
    empty_settings.MILVUS_URI = "https://milvus.invalid:19530"
    empty_settings.MILVUS_AUTH_ENABLED = True
    empty_settings.MILVUS_CA_CERT = "/offline/ca.pem"
    empty_settings.MILVUS_SERVER_NAME = "milvus.invalid"
    empty_settings.MILVUS_DB_NAME = "test_db"
    empty_settings.MILVUS_TOKEN = "test-token" if token else ""
    empty_settings.MILVUS_USER = "test-user"
    empty_settings.MILVUS_PASSWORD = "test-password"
    instance = MilvusService(empty_settings)
    main_thread = threading.get_ident()
    constructor_threads = []

    def construct(**kwargs):
        constructor_threads.append(threading.get_ident())
        return sdk[0]

    try:
        with patch("app.services.milvus_service.MilvusClient", wraps=MilvusClient) as factory:
            factory.side_effect = construct
            await instance.ensure_collection()
            await instance.ensure_collection()
            factory.assert_called_once()
            args = factory.call_args.kwargs
            assert args["uri"] == empty_settings.MILVUS_URI
            assert args["db_name"] == "test_db"
            assert args["timeout"] == 30
            assert args["secure"] is True
            assert args["ca_pem_path"] == "/offline/ca.pem"
            assert args["server_name"] == "milvus.invalid"
            if token:
                assert args["token"] == "test-token"
                assert "password" not in args and "user" not in args
            else:
                assert args["user"] == "test-user"
                assert args["password"] == "test-password"
                assert "token" not in args
        assert constructor_threads[0] != main_thread
    finally:
        await instance.aclose()
    sdk[0].close.assert_called_once()


async def test_local_connection_omits_authentication_options(empty_settings, sdk):
    empty_settings.MILVUS_URI = "http://127.0.0.1:19530"
    empty_settings.MILVUS_AUTH_ENABLED = False
    empty_settings.MILVUS_SECURE = False
    instance = MilvusService(empty_settings)

    try:
        with patch("app.services.milvus_service.MilvusClient") as factory:
            factory.return_value = sdk[0]
            await instance.ensure_collection()
            options = factory.call_args.kwargs
            assert options["uri"] == "http://127.0.0.1:19530"
            assert options["secure"] is False
            assert not {"token", "user", "password"} & options.keys()
    finally:
        await instance.aclose()


async def test_missing_collection_sdk_schema_and_index(service, sdk, empty_settings):
    client = sdk[0]
    client.has_collection.return_value = False
    client.list_indexes.return_value = []
    await service.ensure_collection()
    args = client.create_collection.call_args.kwargs
    assert args["collection_name"] == empty_settings.MILVUS_COLLECTION
    assert args["consistency_level"] == "Strong"
    assert args["timeout"] == empty_settings.MILVUS_TIMEOUT
    schema = args["schema"]
    assert isinstance(schema, CollectionSchema)
    schema.verify()
    assert schema.auto_id is False
    assert json.loads(schema.description) == empty_settings.vector_space.to_dict()
    fields = {field.name: field for field in schema.fields}
    assert fields["media_id"].dtype == DataType.VARCHAR
    assert fields["media_id"].is_primary
    assert fields["embedding"].dtype == DataType.FLOAT_VECTOR
    assert fields["embedding"].params["dim"] == 1024
    assert schema.to_dict()["enable_dynamic_field"] is False
    params = list(client.create_index.call_args.kwargs["index_params"])
    assert len(params) == 1
    assert params[0].field_name == "embedding"
    assert params[0].index_type == "HNSW"
    assert params[0].get_index_configs() == {
        "index_type": "HNSW", "metric_type": "COSINE", "M": 16, "efConstruction": 200,
    }
    client.load_collection.assert_called_once()
    client.drop_collection.assert_not_called()
    client.drop_index.assert_not_called()
    assert await service.get_collection_config() == empty_settings.vector_space.to_dict()


@pytest.mark.parametrize("key,value", [
    ("model", "qwen3-vl-embedding"), ("dimension", 1536),
    ("dimension", 1024.0), ("corpus_instruction_version", "old"),
    ("query_instruction_version", "old"), ("collection", "other_collection"),
    ("model", None),
])
async def test_identity_mismatch_never_overwritten(service, sdk, key, value):
    description = sdk[0].describe_collection.return_value
    metadata = json.loads(description["description"])
    if value is None:
        metadata.pop(key)
    else:
        metadata[key] = value
    description["description"] = json.dumps(metadata)
    with pytest.raises(VectorSpaceMismatchError):
        await service.upsert(**record())
    sdk[0].upsert.assert_not_called()
    sdk[0].create_collection.assert_not_called()
    sdk[0].create_index.assert_not_called()
    sdk[0].load_collection.assert_not_called()
    sdk[0].drop_collection.assert_not_called()
    sdk[0].alter_collection_properties.assert_not_called()


@pytest.mark.parametrize("description", [
    "", "not-json", "[]", "null", "{}",
    json.dumps({"unexpected": "metadata"}),
])
async def test_missing_metadata_is_not_inferred(service, sdk, description):
    sdk[0].describe_collection.return_value["description"] = description
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()


async def test_extra_metadata_is_rejected(service, sdk):
    description = sdk[0].describe_collection.return_value
    metadata = json.loads(description["description"])
    description["description"] = json.dumps({**metadata, "legacy_model": "old"})
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()


@pytest.mark.parametrize("change", [
    {"auto_id": True}, {"enable_dynamic_field": True}, {"consistency_level": 2},
    {"fields": []}, {"collection_name": "other_collection"},
])
async def test_incompatible_collection_schema(service, sdk, change):
    sdk[0].describe_collection.return_value.update(change)
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()


@pytest.mark.parametrize("field,change", [
    ("media_id", {"type": DataType.INT64}),
    ("media_id", {"is_primary": False}),
    ("media_id", {"params": {"max_length": 32}}),
    ("tos_url", {"nullable": True}),
    ("embedding", {"params": {"dim": 768}}),
    ("embedding", {"type": DataType.BINARY_VECTOR}),
])
async def test_incompatible_field(service, sdk, field, change):
    fields = sdk[0].describe_collection.return_value["fields"]
    next(item for item in fields if item["name"] == field).update(change)
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()


@pytest.mark.parametrize("change", [
    {"metric_type": "L2"}, {"index_type": "IVF_FLAT"},
    {"M": "32"}, {"efConstruction": "100"}, {"field_name": "other"},
])
async def test_incompatible_index_is_not_rebuilt(service, sdk, change):
    sdk[0].describe_index.return_value.update(change)
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()
    sdk[0].drop_index.assert_not_called()
    sdk[0].drop_collection.assert_not_called()
    sdk[0].load_collection.assert_not_called()


async def test_nested_index_params_supported(service, sdk):
    index = sdk[0].describe_index.return_value
    index["params"] = {"M": index.pop("M"), "efConstruction": index.pop("efConstruction")}
    await service.ensure_collection()


async def test_failed_index_creation_can_resume_without_drop(service, sdk):
    client = sdk[0]
    client.has_collection.side_effect = [False, True]
    client.list_indexes.return_value = []
    client.create_index.side_effect = [MilvusException(message="failure"), None]
    with pytest.raises(ServiceError):
        await service.ensure_collection()
    await service.ensure_collection()
    client.create_collection.assert_called_once()
    assert client.create_index.call_count == 2
    client.load_collection.assert_called_once()
    client.drop_collection.assert_not_called()


async def test_idempotent_upsert_batch_and_exact_count(service, sdk):
    assert await service.get_vector_count() == 0
    assert await service.upsert(**record()) == "media-1"
    assert await service.upsert(**record(tos_url="tos://sample/updated.png")) == "media-1"
    assert await service.get_vector_count() == 1
    assert sdk[1]["media-1"]["tos_url"] == "tos://sample/updated.png"
    assert await service.batch_upsert([
        record(), record("media-2"), record(tos_url="tos://sample/last.png"),
    ]) == ["media-1", "media-2", "media-1"]
    assert len(sdk[0].upsert.call_args.kwargs["data"]) == 2
    assert sdk[1]["media-1"]["tos_url"] == "tos://sample/last.png"
    assert await service.get_vector_count() == 2
    await service.delete("media-1")
    assert await service.get_vector_count() == 1
    await service.delete("media-1")
    assert await service.get_vector_count() == 1
    sdk[0].get_collection_stats.assert_not_called()
    assert (await service.check_connection())["count_is_exact"] is True


async def test_empty_batch_has_no_sdk_io(service, sdk):
    assert await service.batch_upsert([]) == []
    sdk[0].has_collection.assert_not_called()
    sdk[0].upsert.assert_not_called()


async def test_delete_uses_primary_keys_not_interpolation(service, sdk):
    media_id = 'id" or media_id != "'
    await service.delete(media_id)
    args = sdk[0].delete.call_args.kwargs
    assert args["ids"] == [media_id]
    assert "filter" not in args


@pytest.mark.parametrize("vector", [
    [], [0.0] * 1024, [1.0] * 768, [float("nan")] * 1024,
    [float("inf")] * 1024, [True] * 1024, ["1"] * 1024, None,
])
async def test_vector_boundaries_reject_before_io(service, sdk, vector):
    for operation in (service.upsert(**record(embedding=vector)), service.search(vector)):
        with pytest.raises(ServiceError) as raised:
            await operation
        assert raised.value.service == "milvus"
        assert raised.value.category == "invalid_vector"
    sdk[0].has_collection.assert_not_called()


@pytest.mark.parametrize("change", [
    {"media_id": ""}, {"media_id": 123}, {"media_id": "\u4e2d" * 86},
    {"tos_url": "https://example.invalid/image.png?signature=secret"},
    {"tos_url": "oss://sample/image.png"}, {"tos_url": "tos:///file"},
    {"tos_url": "tos://sample/"}, {"file_type": "unknown"},
    {"model": "qwen3-vl-embedding"},
])
async def test_bad_batch_is_validated_before_any_write(service, sdk, change):
    with pytest.raises(ServiceError):
        await service.batch_upsert([record(), {**record("bad"), **change}])
    sdk[0].upsert.assert_not_called()
    sdk[0].has_collection.assert_not_called()


@pytest.mark.parametrize("reply", [{}, None, {"upsert_count": 0}, {"upsert_count": True}])
async def test_failed_mutation_response_is_not_success(service, sdk, reply):
    sdk[0].upsert.side_effect = None
    sdk[0].upsert.return_value = reply
    with pytest.raises(ServiceError, match="invalid response"):
        await service.upsert(**record())


@pytest.mark.parametrize("reply", [
    [], {}, None, [{}], [{"count(*)": -1}], [{"count(*)": True}],
    [{"count(*)": "0"}], [{"count(*)": 0}, {"count(*)": 1}],
])
async def test_invalid_count_is_not_zero(service, sdk, reply):
    sdk[0].query.side_effect = None
    sdk[0].query.return_value = reply
    with pytest.raises(ServiceError, match="invalid response"):
        await service.get_vector_count()


def hit(media_id, score):
    return {
        "id": media_id, "distance": score,
        "entity": {
            "media_id": media_id, "user_id": "user-1",
            "tos_url": "tos://sample/file.png", "file_type": "image",
        },
    }


async def test_clamp_sort_threshold_and_strong_search(service, sdk):
    sdk[0].search.return_value = [[
        hit("negative", -0.2), hit("middle", 0.5), hit("zero", 0),
        hit("above", 1.01), hit("one", 1),
    ]]
    result = await service.search(record()["embedding"], top_k=200)
    assert [row["score"] for row in result] == [1, 1, 0.5, 0, 0]
    args = sdk[0].search.call_args.kwargs
    assert args["data"] == [record()["embedding"]]
    assert args["anns_field"] == "embedding"
    assert args["consistency_level"] == "Strong"
    assert args["search_params"] == {"metric_type": "COSINE", "params": {"ef": 200}}
    assert args["output_fields"] == ["media_id", "user_id", "tos_url", "file_type"]
    assert args["filter"] == ""
    assert args["timeout"] == 30
    assert [row["score"] for row in await service.search(record()["embedding"], min_score=0.5)] == [1, 1, 0.5]
    assert len(await service.search(record()["embedding"], min_score=1)) == 2


async def test_real_sdk_protobuf_search_response(service, sdk):
    response = schema_pb2.SearchResultData(
        num_queries=1, top_k=1, topks=[1], scores=[0.75], primary_field_name="media_id",
        ids=schema_pb2.IDs(str_id=schema_pb2.StringArray(data=["media-1"])),
        output_fields=["media_id", "user_id", "tos_url", "file_type"],
    )
    for name, value in (
        ("user_id", "user-1"), ("tos_url", "tos://sample/file.png"),
        ("file_type", "image"),
    ):
        response.fields_data.append(schema_pb2.FieldData(
            field_name=name, type=DataType.VARCHAR,
            scalars=schema_pb2.ScalarField(string_data=schema_pb2.StringArray(data=[value])),
        ))
    sdk[0].search.return_value = SearchResult(response)
    result = await service.search(record()["embedding"])
    assert result == [{
        "media_id": "media-1", "user_id": "user-1",
        "tos_url": "tos://sample/file.png",
        "file_type": "image", "score": 0.75,
    }]


@pytest.mark.parametrize("kwargs", [
    {"top_k": 0}, {"top_k": -1}, {"top_k": True}, {"top_k": 1.5},
    {"top_k": 16385}, {"min_score": -0.01}, {"min_score": 1.01},
    {"min_score": float("nan")}, {"min_score": float("inf")}, {"min_score": True},
])
async def test_search_request_boundaries(service, sdk, kwargs):
    with pytest.raises(ServiceError) as raised:
        await service.search(record()["embedding"], **kwargs)
    assert raised.value.category == "invalid_request"
    sdk[0].search.assert_not_called()


@pytest.mark.parametrize("response", [
    [], None, {}, [[{}]], [[hit("bad", float("nan"))]], [[hit("bad", True)]],
])
async def test_malformed_search_response(service, sdk, response):
    sdk[0].search.return_value = response
    with pytest.raises(ServiceError) as raised:
        await service.search(record()["embedding"])
    assert raised.value.category == "invalid_response"


@pytest.mark.parametrize("operation,method", [
    ("ensure_collection", "has_collection"), ("get_vector_count", "query"),
    ("check_connection", "query"), ("delete", "delete"), ("upsert", "upsert"),
    ("search", "search"), ("get_collection_config", "describe_collection"),
])
async def test_cloud_failures_are_redacted_not_empty(service, sdk, operation, method):
    getattr(sdk[0], method).side_effect = MilvusException(
        message="test-password Authorization: token https://host?signature=secret",
    )
    args = {
        "delete": {"media_id": "media-1"}, "upsert": record(),
        "search": {"query_vector": record()["embedding"]},
    }.get(operation, {})
    with pytest.raises(ServiceError) as raised:
        await getattr(service, operation)(**args)
    error = raised.value
    assert error.category == "unavailable"
    assert "test-password" not in str(error)
    assert "signature" not in json.dumps(error.to_dict())
    assert error.__suppress_context__


@pytest.mark.parametrize("error,category", [
    (TimeoutError("secret"), "timeout"),
    (ParamError(message="secret"), "invalid_request"),
    (MilvusException(code=ErrorCode.RATE_LIMIT, message="secret"), "rate_limit"),
    (MilvusException(code=ErrorCode.FORCE_DENY, message="secret"), "permission"),
])
async def test_error_categories(service, sdk, error, category):
    sdk[0].has_collection.side_effect = error
    with pytest.raises(ServiceError) as raised:
        await service.ensure_collection()
    assert raised.value.category == category


@pytest.mark.parametrize("code,category", [
    (grpc.StatusCode.UNAUTHENTICATED, "authentication"),
    (grpc.StatusCode.PERMISSION_DENIED, "permission"),
    (grpc.StatusCode.DEADLINE_EXCEEDED, "timeout"),
])
async def test_grpc_error_categories(service, sdk, code, category):
    class RPCError(grpc.RpcError):
        def code(self):
            return code

    sdk[0].has_collection.side_effect = RPCError()
    with pytest.raises(ServiceError) as raised:
        await service.ensure_collection()
    assert raised.value.category == category


async def test_concurrent_initialization_runs_once(service, sdk):
    await asyncio.gather(*(service.ensure_collection() for _ in range(12)))
    sdk[0].has_collection.assert_called_once()
    sdk[0].load_collection.assert_called_once()


async def test_bounded_workers_cancellation_and_draining_close(empty_settings, sdk):
    empty_settings.CLOUD_IO_MAX_WORKERS = 2
    instance = MilvusService(empty_settings, client=sdk[0])
    await instance.ensure_collection()
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0
    calls = 0

    def query(**kwargs):
        nonlocal active, peak, calls
        with lock:
            calls += 1
            active += 1
            peak = max(peak, active)
            if active == 2:
                started.set()
        assert release.wait(5)
        with lock:
            active -= 1
        return [{"count(*)": 0}]

    sdk[0].query.side_effect = query
    tasks = [asyncio.create_task(instance.get_vector_count()) for _ in range(8)]
    close_task = None
    try:
        assert await asyncio.to_thread(started.wait, 3)
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert instance._executor._work_queue.qsize() == 0
        close_task = asyncio.create_task(instance.aclose())
        await asyncio.sleep(0)
        assert not close_task.done()
        sdk[0].close.assert_not_called()
        release.set()
        await close_task
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert peak == 2
        assert calls == 2
        assert all(isinstance(result, ServiceError) for result in results[2:])
        sdk[0].close.assert_called_once()
        assert instance._executor._shutdown
        await instance.aclose()
        with pytest.raises(ServiceError):
            await instance.get_vector_count()
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await instance.aclose()


async def test_unused_close_and_cancelled_close_still_release_client(empty_settings, sdk):
    unused = MilvusService(empty_settings)
    await unused.aclose()
    assert unused._executor is None
    started = threading.Event()
    release = threading.Event()

    def close():
        started.set()
        assert release.wait(5)

    sdk[0].close.side_effect = close
    instance = MilvusService(empty_settings, client=sdk[0])
    task = asyncio.create_task(instance.aclose())
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await instance.aclose()
    sdk[0].close.assert_called_once()


async def test_close_failure_is_redacted_and_pool_is_shutdown(empty_settings, sdk):
    sdk[0].close.side_effect = RuntimeError("private-token")
    instance = MilvusService(empty_settings, client=sdk[0])
    with pytest.raises(ServiceError) as raised:
        await instance.aclose()
    assert "private-token" not in str(raised.value)
    assert instance._executor._shutdown


async def test_centralized_index_settings_and_snapshot(empty_settings, sdk):
    empty_settings.MILVUS_HNSW_M = 32
    empty_settings.MILVUS_HNSW_EF_CONSTRUCTION = 300
    empty_settings.MILVUS_SEARCH_EF = 250
    empty_settings.MILVUS_TIMEOUT = 7
    sdk[0].list_indexes.return_value = []
    sdk[0].describe_index.return_value.update(M="32", efConstruction="300")
    instance = MilvusService(empty_settings, client=sdk[0])
    empty_settings.MILVUS_TIMEOUT = 999
    try:
        await instance.search(record()["embedding"])
        index = list(sdk[0].create_index.call_args.kwargs["index_params"])[0]
        assert index.get_index_configs()["M"] == 32
        assert index.get_index_configs()["efConstruction"] == 300
        assert sdk[0].search.call_args.kwargs["search_params"]["params"]["ef"] == 250
        assert sdk[0].search.call_args.kwargs["timeout"] == 7
    finally:
        await instance.aclose()


async def test_failed_load_is_not_cached(service, sdk):
    sdk[0].load_collection.side_effect = [TimeoutError(), None]
    with pytest.raises(ServiceError) as raised:
        await service.ensure_collection()
    assert raised.value.category == "timeout"
    await service.ensure_collection()
    assert sdk[0].load_collection.call_count == 2
    sdk[0].drop_collection.assert_not_called()


async def test_collection_config_is_read_from_server_not_guessed(service, sdk):
    await service.ensure_collection()
    sdk[0].describe_collection.return_value["description"] = "{}"
    with pytest.raises(VectorSpaceMismatchError):
        await service.get_collection_config()


@pytest.mark.parametrize("value", [1024.5, 1024.0, True, None])
async def test_field_dimension_must_be_exact(service, sdk, value):
    sdk[0].describe_collection.return_value["fields"][-1]["params"]["dim"] = value
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()


async def test_invalid_utf8_is_a_service_error(service):
    with pytest.raises(ServiceError) as raised:
        await service.delete("\ud800")
    assert raised.value.category == "invalid_request"


@pytest.mark.parametrize("value", [None, {}, {"params": "invalid"}])
async def test_missing_or_malformed_index_description(service, sdk, value):
    sdk[0].describe_index.return_value = value
    with pytest.raises(VectorSpaceMismatchError):
        await service.ensure_collection()
