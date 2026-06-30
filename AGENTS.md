# AGENTS.md — fms-odata-py

## Overview

Synchronous Python client for the FileMaker Server OData v4 API. Functional
equivalent of [fms-odata-js](https://github.com/fsans/fms-odata-js). Depends
on [`fms-odata-spec`](https://pypi.org/project/fms-odata-spec/) for shared
types, error hierarchy, auth helpers, and URL literal formatting.

## Build commands

- `pip install -e ".[dev]"` — install in editable mode with dev deps
- `python -m build` — build sdist + wheel
- `pytest` — run test suite (162 tests, offline, uses httpx MockTransport)

## Test commands

- `pytest` — all tests
- `pytest tests/test_query.py` — single module
- `pytest -q` — quiet mode

## Key files

- `src/fms_odata/client.py` — `FMSODataClient` entrypoint, version detection, feature gating
- `src/fms_odata/http.py` — transport layer (auth, timeout, 401 retry, error parsing)
- `src/fms_odata/query.py` — fluent query builder + `Filter`/`FilterFactory`
- `src/fms_odata/entity.py` — `EntityRef` (CRUD, containers, scripts, `$ref`)
- `src/fms_odata/scripts.py` — script invocation (3 scopes + FMSID)
- `src/fms_odata/metadata.py` — `$metadata` CSDL parser + version detection
- `src/fms_odata/containers.py` — container field I/O (bytes + streaming)
- `src/fms_odata/batch.py` — `$batch` multipart composer
- `src/fms_odata/schema.py` — schema DDL
- `src/fms_odata/webhooks.py` — webhook management
- `src/fms_odata/url.py` — OData URL encoding helpers (reuses spec-py)
- `src/fms_odata/types.py` — `FMSODataOptions`, `RequestOptions`, `TokenProvider`

## Key conventions

- **Synchronous only (v0.1.0).** No async code yet. The transport/query/entity
  layers are structured to allow a future `AsyncFMSODataClient` as a thin
  parallel class — do not introduce I/O calls into `query.py`, `entity.py`,
  or `url.py`.
- **Reuse spec-py types.** Error classes (`FMODataError`, `FMScriptError`,
  `FMAuthError`, etc.), auth helpers (`basic_auth`, `fmid_auth`), URL literal
  formatting (`escape_string_literal`, `format_literal`), and script response
  parsing are sourced from `fms_odata_spec`. Do not redefine them locally.
- **`from_` not `from`.** The query entry point is `db.from_(entity_set)`
  because `from` is a Python keyword. `from_entity` is a readable alias.
- **`verify_ssl` is Python-only.** No equivalent in the TS client (TS relies
  on the runtime's `fetch`). Added here because httpx exposes it directly and
  FMS self-signed certs are common. Mirrors `FM_VERIFY_SSL` env var naming.
- **`transport` replaces `fetch`.** Test injection uses `httpx.MockTransport`
  via the `transport` parameter, not a `fetch` function.
- **No deprecated aliases.** The TS `FMOData`/`FMODataError` backward-compat
  aliases are not ported (clean slate, no Python legacy users).

## Commit message format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation
- `test:` — tests
- `refactor:` — code refactoring
- `chore:` — build/tooling

## Pre-PR checklist

- [ ] Tests pass: `pytest`
- [ ] Build succeeds: `python -m build`
- [ ] Import works: `python -c "import fms_odata"`
