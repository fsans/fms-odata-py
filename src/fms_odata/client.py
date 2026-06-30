"""Main entrypoint: :class:`FMSODataClient`.

Mirrors ``src/client.ts`` in fms-odata-js. ``FMSODataClient`` is the
entrypoint for all OData operations against a FileMaker Server database:
query/CRUD, script invocation, container I/O, ``$metadata`` introspection,
schema DDL, webhooks, and ``$batch`` operations.

Synchronous only for v0.1.0. An ``AsyncFMSODataClient`` is planned but not
yet implemented; the transport/query-builder internals are structured to
allow it as a thin parallel class (see :mod:`fms_odata.http`).
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

import httpx

from fms_odata_spec import (
    FM_VERSION_MATRIX,
    FMVersionInfo,
    FMVersionMajor,
    FMServerVersion,
    has_feature as spec_has_feature,
)

from .batch import Batch
from .http import HttpClientContext, HttpRequestOptions, execute_json, execute_request
from .metadata import MetadataFetcher, MetadataOptions, ODataMetadata
from .query import Query
from .schema import SchemaEditor
from .scripts import ScriptResult, run_script_at_database, run_script_by_id_at_database
from .types import FMSODataOptions, TokenProvider
from .webhooks import WebhookManager

__all__ = ["FMSODataClient"]


class FMSODataClient:
    """Entrypoint for all OData operations against a FileMaker Server database.

    Args:
        host: Base FMS host, e.g. ``https://fms.example.com`` (trailing
            slashes stripped).
        database: FileMaker database (solution) name.
        token: Bearer token, ``Basic ...`` / ``FMID ...`` header value, or a
            resolver callable. Bare strings are prefixed with ``Bearer ``.
        on_unauthorized: Invoked once on HTTP 401 before a single retry.
        transport: Injectable httpx transport (for testing/mocking). Defaults
            to a standard httpx transport.
        timeout_ms: Per-request timeout in milliseconds.
        verify_ssl: Whether to verify TLS certificates (default ``True``).

    Example::

        from fms_odata import FMSODataClient
        from fms_odata_spec import basic_auth

        db = FMSODataClient(
            host="https://fms.example.com",
            database="Contacts",
            token=basic_auth("admin", "secret"),
            timeout_ms=15_000,
        )
        result = db.from("contact").select("id", "name").top(50).get()
    """

    def __init__(
        self,
        *,
        host: str,
        database: str,
        token: TokenProvider,
        on_unauthorized: Optional[Callable[[], None]] = None,
        transport: Optional[httpx.BaseTransport] = None,
        timeout_ms: Optional[int] = None,
        verify_ssl: bool = True,
    ) -> None:
        if not host:
            raise TypeError("FMSODataClient: `host` is required")
        if not database:
            raise TypeError("FMSODataClient: `database` is required")
        if token is None:
            raise TypeError("FMSODataClient: `token` is required")

        self.host = host.rstrip("/")
        self.database = database
        self.base_url = f"{self.host}/fmi/odata/v4/{_quote_database(database)}"
        self.timeout_ms = timeout_ms

        # Build the httpx client with the injected transport (if any) and
        # verify_ssl. The client owns the connection pool.
        client_kwargs: dict = {"verify": verify_ssl}
        if transport is not None:
            client_kwargs["transport"] = transport
        self._httpx_client = httpx.Client(**client_kwargs)

        self._ctx = HttpClientContext(
            token=token,
            on_unauthorized=on_unauthorized,
            client=self._httpx_client,
            timeout_ms=timeout_ms,
        )
        self._metadata_fetcher: Optional[MetadataFetcher] = None
        self._schema_editor: Optional[SchemaEditor] = None
        self._webhook_manager: Optional[WebhookManager] = None
        self._detected_version: Optional[str] = None
        self._detected_server_version: Optional[FMServerVersion] = None
        self._version_resolved = False

    # -- query entry point ------------------------------------------------

    def from_(self, entity_set: str) -> Query:
        """Start a query against the given entity set (FileMaker layout name).

        ``from_`` is used because ``from`` is a Python keyword. An alias
        ``from_entity`` is also provided for readability.
        """
        if not entity_set:
            raise TypeError("FMSODataClient.from_: entity_set is required")
        return Query(self.base_url, entity_set, self)

    # Readable alias (some prefer this over the trailing-underscore form).
    from_entity = from_

    # -- low-level escape hatches -----------------------------------------

    def request(self, path_or_url: str, opts: Optional[HttpRequestOptions] = None) -> Any:
        """Low-level: execute a raw request, return parsed JSON."""
        return execute_json(self._ctx, self._resolve_url(path_or_url), opts)

    def raw_request(self, path_or_url: str, opts: Optional[HttpRequestOptions] = None) -> httpx.Response:
        """Low-level: return the raw ``httpx.Response`` (for binary/streaming)."""
        return execute_request(self._ctx, self._resolve_url(path_or_url), opts)

    # -- scripts ----------------------------------------------------------

    def script(self, name: str, parameter: Optional[str] = None) -> ScriptResult:
        """Invoke a FileMaker script at database scope."""
        return run_script_at_database(self, name, parameter)

    def script_by_id(self, fmsid: int, parameter: Optional[str] = None) -> ScriptResult:
        """Invoke a FileMaker script by its immutable FMSID (v26+)."""
        return run_script_by_id_at_database(self, fmsid, parameter)

    # -- metadata ---------------------------------------------------------

    def metadata(self, opts: Optional[MetadataOptions] = None) -> ODataMetadata:
        """Fetch and parse the OData CSDL $metadata. Results are cached."""
        if self._metadata_fetcher is None:
            self._metadata_fetcher = MetadataFetcher(self._ctx, self.base_url)
        return self._metadata_fetcher.fetch(opts)

    def metadata_xml(self, opts: Optional[MetadataOptions] = None) -> str:
        """Fetch the raw $metadata XML (escape hatch for debugging)."""
        if self._metadata_fetcher is None:
            self._metadata_fetcher = MetadataFetcher(self._ctx, self.base_url)
        return self._metadata_fetcher.fetch_xml(opts)

    # -- version detection & feature gating -------------------------------

    def version(self) -> Optional[str]:
        """Detect the FileMaker Server major version (``'19'``/``'21'``/``'22'``/``'26'``/``'future'``).

        Returns ``None`` if the version cannot be determined. Cached for the
        lifetime of this client instance.
        """
        if self._version_resolved:
            return self._detected_version
        try:
            sv = self.server_version()
            if sv is None:
                self._detected_version = None
            else:
                major = str(sv.major)
                self._detected_version = major if major in FM_VERSION_MATRIX else "future"
        except Exception:
            self._detected_version = None
        self._version_resolved = True
        return self._detected_version

    def server_version(self) -> Optional[FMServerVersion]:
        """Get the full parsed FileMaker Server version. Cached."""
        if self._version_resolved:
            return self._detected_server_version
        try:
            xml = self.metadata_xml()
            from fms_odata_spec import parse_server_version

            self._detected_server_version = parse_server_version(xml)
        except Exception:
            self._detected_server_version = None
        self._version_resolved = True
        return self._detected_server_version

    def version_info(self) -> Optional[FMVersionInfo]:
        """Get the full version info (feature flags + query option flags)."""
        v = self.version()
        if v is None:
            return None
        return FM_VERSION_MATRIX.get(v)

    def has_feature(self, feature: str) -> bool:
        """Check if the server supports a specific feature."""
        v = self.version()
        if v is None:
            return False
        return spec_has_feature(v, feature)

    # -- schema DDL -------------------------------------------------------

    def schema(self) -> SchemaEditor:
        """Get a :class:`SchemaEditor` handle for DDL operations."""
        if self._schema_editor is None:
            self._schema_editor = SchemaEditor(self)
        return self._schema_editor

    def create_table(self, params: dict) -> Any:
        return self.schema().create_table(params)

    def add_fields(self, params: dict) -> Any:
        return self.schema().add_fields(params)

    def delete_table(self, table_name: str, *, confirm: bool = False) -> None:
        self.schema().delete_table(table_name, confirm=confirm)

    def delete_field(self, table_name: str, field_name: str, *, confirm: bool = False) -> None:
        self.schema().delete_field(table_name, field_name, confirm=confirm)

    def create_index(self, table_name: str, field_name: str) -> Any:
        return self.schema().create_index(table_name, field_name)

    def delete_index(self, table_name: str, field_name: str) -> None:
        self.schema().delete_index(table_name, field_name)

    # -- webhooks ---------------------------------------------------------

    def webhooks(self) -> WebhookManager:
        """Get a :class:`WebhookManager` handle (FMS 2023+ / v21)."""
        if self._webhook_manager is None:
            self._webhook_manager = WebhookManager(self)
        return self._webhook_manager

    def create_webhook(self, params: dict) -> Any:
        return self.webhooks().create(params)

    def remove_webhook(self, webhook_id: str) -> Any:
        return self.webhooks().remove(webhook_id)

    def get_webhook(self, webhook_id: str) -> Any:
        return self.webhooks().get(webhook_id)

    def get_all_webhooks(self) -> Any:
        return self.webhooks().get_all()

    def invoke_webhook(self, webhook_id: str) -> Any:
        return self.webhooks().invoke(webhook_id)

    # -- batch ------------------------------------------------------------

    def batch(self) -> Batch:
        """Create a new ``$batch`` builder."""
        return Batch(self)

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        """Close the underlying httpx client and release connection pool."""
        self._httpx_client.close()

    def __enter__(self) -> "FMSODataClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- internal ---------------------------------------------------------

    def _resolve_url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        if path_or_url.startswith("/"):
            return f"{self.base_url}{path_or_url}"
        return f"{self.base_url}/{path_or_url}"


def _quote_database(database: str) -> str:
    from urllib.parse import quote

    return quote(database, safe="")
