"""Public types for fms-odata-py.

Mirrors the option shapes from ``src/types.ts`` in fms-odata-js, adapted to
Python idioms:

- ``AbortSignal`` is dropped (sync-only client; cancellation is deferred to
  the planned async client).
- ``fetch`` injection is replaced by ``transport: httpx.BaseTransport``.
- ``verify_ssl`` is a Python-only addition (httpx exposes TLS verification
  directly; mirrors the ``FM_VERIFY_SSL`` env var used by the MCP servers).
"""

from __future__ import annotations

from typing import Callable, Optional, Union

import httpx

__all__ = [
    "TokenProvider",
    "FMSODataOptions",
    "RequestOptions",
]

#: Auth token: a static header value (e.g. ``"Basic dXNlcjpwYXNz"``) or a
#: callable that returns one. The callable form supports token refresh;
#: in the sync client it must be a plain (non-coroutine) callable.
TokenProvider = Union[str, Callable[[], str]]


class FMSODataOptions:
    """Configuration for :class:`fms_odata.client.FMSODataClient`.

    Attributes:
        host: Base FMS host, e.g. ``https://fms.example.com`` (trailing
            slashes are stripped).
        database: FileMaker database (solution) name.
        token: Bearer token, ``Basic ...`` / ``FMID ...`` header value, or a
            resolver callable. Bare strings are prefixed with ``Bearer ``.
        on_unauthorized: Invoked once on HTTP 401 before a single retry.
        transport: Injectable httpx transport (for testing/mocking). Defaults
            to a standard httpx transport.
        timeout_ms: Per-request timeout in milliseconds.
        verify_ssl: Whether to verify TLS certificates. Defaults to ``True``.
            Set to ``False`` for FMS deployments using self-signed certs.
    """

    __slots__ = (
        "host",
        "database",
        "token",
        "on_unauthorized",
        "transport",
        "timeout_ms",
        "verify_ssl",
    )

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
        self.host = host
        self.database = database
        self.token = token
        self.on_unauthorized = on_unauthorized
        self.transport = transport
        self.timeout_ms = timeout_ms
        self.verify_ssl = verify_ssl


class RequestOptions:
    """Common request-level options accepted by every method.

    The TS ``signal?: AbortSignal`` field is intentionally absent: cancellation
    is an async-shaped concern and is deferred to the planned
    ``AsyncFMSODataClient``. The sync client uses ``timeout_ms`` only.
    """

    __slots__ = ()

    def __init__(self, **_: object) -> None:  # pragma: no cover - placeholder
        pass
