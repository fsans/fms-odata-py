"""fms-odata-py -- Synchronous Python client for the FileMaker Server OData v4 API.

Functional equivalent of `fms-odata-js <https://github.com/fsans/fms-odata-js>`_.
This is a **synchronous** client (v0.2.0); async support is planned but not
yet implemented. All shared types are sourced from
`fms-odata-spec <https://pypi.org/project/fms-odata-spec/>`_ -- spec types are
not redefined locally.

Quick start::

    from fms_odata import FMSODataClient
    from fms_odata_spec import basic_auth

    db = FMSODataClient(
        host="https://fms.example.com",
        database="Contacts",
        token=basic_auth("admin", "secret"),
    )
    result = db.from_("contact").select("id", "name").top(50).get()
    for row in result.value:
        print(row)
"""

from __future__ import annotations

from .client import FMSODataClient
from .query import Filter, FilterFactory, Query, QueryResult, filter_factory
from .entity import EntityRef, EntityWriteOptions
from .scripts import ScriptInvoker, ScriptResult
from .metadata import MetadataFetcher, MetadataOptions, ODataMetadata
from .containers import ContainerDownload, ContainerRef, FM_CONTAINER_SUPPORTED_MIME_TYPES
from .batch import Batch, BatchOpResult, BatchResult, Changeset
from .schema import SchemaEditor
from .webhooks import WebhookManager
from .http import HttpRequestOptions
from .types import FMSODataOptions, RequestOptions, TokenProvider
from .url import (
    ODataLiteral,
    build_query_string,
    encode_path_segment,
    escape_string_literal,
    format_date_time,
    format_literal,
    odata_encode,
    parse_date_time,
)

# Re-export spec types commonly used alongside the client, so callers can
# import everything from one place if they wish.
from fms_odata_spec import (
    FMAuthError,
    FMODataError,
    FMNotFoundError,
    FMScriptError,
    FMValidationError,
    ODataErrorBody,
    RequestRef,
    basic_auth,
    bearer_auth,
    is_fm_odata_error,
    is_fm_script_error,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # client
    "FMSODataClient",
    "FMSODataOptions",
    "TokenProvider",
    "RequestOptions",
    # query
    "Query",
    "QueryResult",
    "Filter",
    "FilterFactory",
    "filter_factory",
    # entity
    "EntityRef",
    "EntityWriteOptions",
    # scripts
    "ScriptInvoker",
    "ScriptResult",
    # metadata
    "MetadataFetcher",
    "MetadataOptions",
    "ODataMetadata",
    # containers
    "ContainerDownload",
    "ContainerRef",
    "FM_CONTAINER_SUPPORTED_MIME_TYPES",
    # batch
    "Batch",
    "BatchOpResult",
    "BatchResult",
    "Changeset",
    # schema
    "SchemaEditor",
    # webhooks
    "WebhookManager",
    # http
    "HttpRequestOptions",
    # url helpers
    "ODataLiteral",
    "build_query_string",
    "encode_path_segment",
    "escape_string_literal",
    "format_date_time",
    "format_literal",
    "odata_encode",
    "parse_date_time",
    # spec re-exports (errors + auth)
    "FMODataError",
    "FMScriptError",
    "FMAuthError",
    "FMNotFoundError",
    "FMValidationError",
    "ODataErrorBody",
    "RequestRef",
    "basic_auth",
    "bearer_auth",
    "is_fm_odata_error",
    "is_fm_script_error",
]
