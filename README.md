# fms-odata-py

Synchronous Python client for the FileMaker Server OData v4 API.

Functional equivalent of [fms-odata-js](https://github.com/fsans/fms-odata-js).

[![PyPI](https://img.shields.io/pypi/v/fms-odata-py)](https://pypi.org/project/fms-odata-py/)
[![Python](https://img.shields.io/pypi/pyversions/fms-odata-py)](https://pypi.org/project/fms-odata-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Status

**v0.2.0** — synchronous client only. An async variant (`AsyncFMSODataClient`)
is planned but not yet implemented. The transport and query-builder internals
are structured to allow it as a thin parallel class (see
[Architecture](#architecture)).

## Installation

```bash
pip install fms-odata-py
```

Dependencies:

- [`httpx`](https://www.python-httpx.org/) >= 0.27 — HTTP client
- [`fms-odata-spec`](https://pypi.org/project/fms-odata-spec/) >= 2.0.1 — shared types, error hierarchy, auth helpers, URL literal formatting

## Quick start

```python
from fms_odata import FMSODataClient
from fms_odata_spec import basic_auth

db = FMSODataClient(
    host="https://fms.example.com",
    database="Contacts",
    token=basic_auth("admin", "secret"),
    timeout_ms=15_000,
)

# Query
result = db.from_("contact").select("id", "name").top(50).get()
for row in result.value:
    print(row["id"], row["name"])

# Filter
from fms_odata import filter_factory

active = (
    db.from_("contact")
    .select("id", "name")
    .filter(lambda f: f.eq("status", "active").and_(f.gt("balance", 0)))
    .orderby("name")
    .top(25)
    .get()
)

# Single entity CRUD
contact = db.from_("contact").by_key(7)
row = contact.get()
contact.patch({"city": "Girona"})
contact.delete()

# Scripts
result = db.script("SendEmail", parameter="contact:7")
print(result.result_parameter)

# Containers
photo = db.from_("contact").by_key(7).container("photo").get()
with open("photo.png", "wb") as fh:
    fh.write(photo.content)

# Metadata & version detection
meta = db.metadata()
print(db.version())        # '20', '21', '22', '26', 'future', or None
print(db.has_feature("apply_aggregation"))

db.close()
```

Use as a context manager for automatic cleanup:

```python
with FMSODataClient(host=..., database=..., token=...) as db:
    ...
```

## API reference

### `FMSODataClient`

Entrypoint for all OData operations.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `host` | `str` | yes | FMS host, e.g. `https://fms.example.com` (trailing slashes stripped). |
| `database` | `str` | yes | FileMaker database (solution) name. URL-encoded into base URL. |
| `token` | `str \| Callable[[], str]` | yes | Auth header value or resolver. Bare strings get `Bearer ` prefixed; scheme-prefixed (`Basic ...`, `Bearer ...`) pass through. |
| `on_unauthorized` | `Callable[[], None]` | no | Invoked once on HTTP 401, then a single retry. |
| `transport` | `httpx.BaseTransport` | no | Injectable transport (for testing/mocking). |
| `timeout_ms` | `int` | no | Per-request timeout in milliseconds. |
| `verify_ssl` | `bool` | no | Verify TLS certificates (default `True`). Set to `False` for self-signed certs. |

**Methods:**

| Method | Description |
|---|---|
| `from_(entity_set)` / `from_entity(entity_set)` | Start a fluent `Query` against an entity set. (`from_` because `from` is a Python keyword.) |
| `request(path_or_url, opts?)` | Low-level: execute a raw request, return parsed JSON. |
| `raw_request(path_or_url, opts?)` | Low-level: return raw `httpx.Response` (for binary/streaming). |
| `script(name, parameter?)` | Invoke a FileMaker script at database scope. |
| `script_by_id(fmsid, parameter?)` | Invoke a script by immutable FMSID (v26+). |
| `metadata(opts?)` | Fetch and parse `$metadata` CSDL. Cached. |
| `metadata_xml(opts?)` | Fetch raw `$metadata` XML. |
| `version()` | Detect major version (`'20'`/`'21'`/`'22'`/`'26'`/`'future'`/`None`). Cached. |
| `server_version()` | Full parsed `FMServerVersion`. Cached. |
| `version_info()` | Full `FMVersionInfo` (feature flags + query-option flags). |
| `has_feature(feature)` | Boolean feature gate. |
| `schema()` | Get a `SchemaEditor` handle for DDL. |
| `create_table(params)` / `add_fields(params)` / ... | Convenience DDL proxies. |
| `webhooks()` | Get a `WebhookManager` handle (v22+). |
| `create_webhook(params)` / `remove_webhook(id)` / `delete_webhook(id)` / ... | Convenience webhook proxies. |
| `batch()` | Create a `$batch` builder. |
| `close()` | Close the underlying httpx client. |

### `Query`

Fluent builder. Methods mutate and return `self` for chaining.

| Method | OData param | Notes |
|---|---|---|
| `select(*fields)` | `$select` | Cumulative; commas kept literal. |
| `filter(input)` | `$filter` | Accepts `Filter`, raw string, or `Callable[[FilterFactory], Filter]`. Multiple calls AND together. |
| `or_(input)` | `$filter` | OR with existing filter. |
| `expand(name, build?)` | `$expand` | Nested options via callback. |
| `orderby(field, dir='asc')` | `$orderby` | Cumulative. |
| `top(n)` | `$top` | Non-negative integer. |
| `skip(n)` | `$skip` | Non-negative integer. |
| `count(enabled=True)` | `$count` | |
| `search(term)` | `$search` | Verbatim. |
| `apply(expr)` | `$apply` | Raw expression (v22+). |
| `aggregate(expressions)` | `$apply` | Builds `aggregate(...)`. |
| `group_by(fields, agg?)` | `$apply` | Builds `groupby((...),aggregate(...))`. |
| `to_url()` | — | Serialize to absolute URL. |
| `by_key(key)` | — | Returns `EntityRef`. |
| `create(body)` | POST | Create entity; returns echoed row. |
| `get()` | GET | Execute; returns `QueryResult`. |
| `script(name, parameter?)` | POST | Script at entity-set scope. |

### `EntityRef`

Single-entity handle from `Query.by_key(key)`.

| Method | HTTP | Notes |
|---|---|---|
| `to_url()` | — | `baseUrl/EntitySet(key)`. |
| `get()` | GET | Returns parsed row. |
| `field_value(name)` | GET | Unwraps `{value: ...}`. |
| `patch(body, opts?)` | PATCH | `Prefer: return=minimal` by default; `return_representation=True` for full row. `if_match` for ETag. |
| `delete(opts?)` | DELETE | Resolves on 204. |
| `script(name, parameter?)` | POST | Record-scope script. |
| `container(field)` | — | Returns `ContainerRef`. |
| `get_refs(nav_property)` | GET | `.../navProperty/$ref`. |
| `add_ref(nav_property, target_url)` | POST | Add relationship. |
| `set_ref(nav_property, target_url)` | PUT | Replace relationship. |
| `remove_ref(nav_property, target_url)` | DELETE | Remove relationship. |

### `ContainerRef`

Container field I/O. Supported MIME types: PNG, JPEG, GIF, TIFF, PDF.

| Method | Description |
|---|---|
| `get()` | Download into memory as `bytes`. Returns `ContainerDownload`. |
| `get_stream(chunk_size=1024)` | Stream as `Iterator[bytes]` (for large files). |
| `upload(data, content_type?, filename?, encoding='binary')` | Upload. `binary` (PATCH `.../field`) or `base64` (PATCH `.../EntitySet(key)` with JSON). MIME sniffed from magic bytes if omitted. |
| `delete()` | Clear container via `{field: null}`. |

### `Batch`

`$batch` multipart operations.

| Method | Description |
|---|---|
| `add(entity_set, query?)` | Add a read (GET) operation. |
| `changeset(build?)` | Add an atomic changeset. `Changeset` supports `create()`, `patch()`, `delete()`. |
| `serialize()` | Serialize to multipart body (returns `{'boundary', 'body'}`). |
| `send()` | Execute and return `BatchResult` with ordered `responses` list. |

### Errors

Reused from `fms-odata-spec` (single hierarchy, not duplicated):

```
Exception
└── FMODataError              (base — status, code, odata_error, request)
    ├── FMScriptError         (script_error, script_result)
    ├── FMAuthError           (status=401)
    ├── FMNotFoundError       (status=404)
    └── FMValidationError     (status=400)
```

Type guards: `is_fm_odata_error(err)`, `is_fm_script_error(err)`.

## Architecture

```
src/fms_odata/
├── __init__.py        Public API re-exports
├── client.py          FMSODataClient — main entrypoint
├── types.py           FMSODataOptions, RequestOptions, TokenProvider
├── http.py            Transport layer (auth, timeout, 401 retry, error parsing)
├── url.py             OData URL encoding helpers (reuses spec-py)
├── query.py           Fluent query builder + Filter/FilterFactory
├── entity.py          EntityRef — single-entity CRUD
├── scripts.py         Script invocation (3 scopes + FMSID)
├── metadata.py        $metadata CSDL parser + version detection
├── containers.py      Container field I/O (bytes + streaming)
├── batch.py           $batch multipart composer
├── schema.py          Schema DDL (FileMaker_Tables, FileMaker_Indexes)
└── webhooks.py        Webhook management
```

**No I/O leakage in query/entity/model layers.** The only I/O lives in
`http.py` (`execute_request` / `execute_json`). This is deliberate: when the
async client is added, it will be a thin `AsyncFMSODataClient` that reuses the
same query-builder/entity logic and swaps the transport for an
`httpx.AsyncClient`-based equivalent.

## Parity with fms-odata-js

| TS (fms-odata-js) | Python (fms-odata-py) | Notes |
|---|---|---|
| `new FMSOData(options)` | `FMSODataClient(...)` | Keyword-only args. |
| `options.fetch` | `options.transport` | `httpx.BaseTransport` injection (replaces `fetch`). |
| `options.signal` (AbortSignal) | — | Dropped. Cancellation is deferred to async client. |
| — | `options.verify_ssl` | Python-only addition (httpx exposes TLS verification). |
| `db.from(entitySet)` | `db.from_(entitySet)` / `db.from_entity(...)` | `from_` because `from` is a Python keyword. |
| `Filter` / `filterFactory` | `Filter` / `filter_factory` | `filter_factory.eq(...)` etc. `and_`/`or_`/`not_` (trailing underscore). |
| `entity.patch(body, {returnRepresentation})` | `entity.patch(body, EntityWriteOptions(return_representation=...))` | |
| `entity.container(field).get()` → `Blob` | `entity.container(field).get()` → `bytes` | No `Blob` in Python. |
| `entity.container(field).getStream()` → `ReadableStream` | `entity.container(field).get_stream()` → `Iterator[bytes]` | httpx `iter_bytes()`. |
| `FMSODataError` / `FMScriptError` (local) | `FMODataError` / `FMScriptError` (from spec-py) | Reused hierarchy, not duplicated. |
| `batch.send()` → per-op Promise handles | `batch.send()` → `BatchResult.responses` (indexed list) | Sync idiom: no Promise equivalent. |
| `FMOData` / `FMODataError` deprecated aliases | — | Skipped (clean slate, no legacy). |
| `basicAuth(user, pass)` | `basic_auth(user, pass)` | From `fms_odata_spec`. |
| `bearerAuth(token)` | `bearer_auth(token)` | From `fms_odata_spec`. |

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest                  # 168 tests
python -m build         # sdist + wheel
```

## License

MIT
