# Offline Backend Tests

From the repository root:

```sh
.tools/venv/bin/python -m pip install -r backend/requirements-test.txt
.tools/venv/bin/python -m pytest -c backend/pytest.ini backend/tests
```

Run only the shared T1 contract tests:

```sh
.tools/venv/bin/python -m pytest -c backend/pytest.ini backend/tests/test_public_contracts.py
```

`conftest.py` removes `APP_ENV_FILE` before collection and blocks DNS and outbound
socket connections, including collection-time calls. Do not remove that guard to
make a test pass. Inject the `mock_tos_client`, `mock_milvus_client`,
`mock_ark_transport`, or `mock_cloud_services` fixtures. HTTP route tests should
use an in-process ASGI transport. Real cloud acceptance belongs in a separate,
explicitly authorized workflow, not in this suite.

`empty_settings` clears known configuration environment variables for a test.
Fixtures and test inputs must contain synthetic values only. Never read the
developer's real `.env`. Tests may explicitly load `.env.example`.

## Shared Contracts

- `app.config.Settings`: process environment by default; dotenv is opt-in through
  `APP_ENV_FILE`. `require_config(service)` is called at service use, not import.
- `app.config.get_model_catalog(config)` returns the `data.model_catalog` object
  for `GET /api/system/config`. Outer response stays `code/message/data`; data
  also has `apiPrefix`, `appName`, `version`.
- Catalog keys: `embedding_models` and `tag_models` are maps keyed by exact model
  ID; `defaults` has `embedding_model`, `embedding_dimension`, `tag_model`,
  `text_search_min_score`; `vector_space` is `VectorSpace.to_dict()`.
- Vector-space keys: `model`, `dimension`, `corpus_instruction_version`,
  `query_instruction_version`, `collection`. All keys must match. Missing metadata
  is incompatible, not a signal to infer the model or recreate a collection.
- `app.services.contracts`: all I/O methods are async; implementations provide
  `aclose()`. Sync SDK clients run in a bounded executor controlled by
  `CLOUD_IO_MAX_WORKERS`. Constructors never connect. The application lifespan
  owns and closes instances, including user-specific instances.
- `UserSettingsUpdate.updates()` excludes omitted, null and blank secret values.
  User responses expose only `*_masked` credential fields, including the TOS
  access-key ID and optional security token. Model fields are globally constrained.
- `ServiceError.to_dict()` is safe public metadata. Never serialize upstream
  exceptions, raw response bodies, request headers or signed URL queries.
- TOS `check_connection` and each Ark model service's `check_connection` return
  `{"status": "ok"}` on success and raise `ServiceError` on failure. Readiness must
  not call Ark. The explicit Ark connection-test route checks both model services
  independently and preserves each result.
