"""HTTP transport layer for fms-odata-py.

Synchronous only for v0.1.0. Built on ``httpx.Client``.

.. note::

   **Async intent (for a future ``AsyncFMSODataClient``):** This module is
   structured so that the query-builder, model, and URL-encoding logic
   (in :mod:`fms_odata.query`, :mod:`fms_odata.entity`, :mod:`fms_odata.url`)
   have **no I/O leakage** -- they build URLs and request payloads as pure
   data, never performing HTTP themselves. The only I/O lives here in
   :func:`execute_request` / :func:`execute_json`.

   When the async client is added, it will be a thin parallel class that
   reuses the same query-builder/model logic and swaps this transport for an
   ``httpx.AsyncClient``-based equivalent. No rewrite of the query/entity
   layers will be needed. Do not introduce I/O calls into those modules.

Responsibilities (mirrors ``src/http.ts`` in fms-odata-js):

- Authorization header resolution (Basic or Bearer/OAuth, auto-detected).
- Timeout handling via httpx.
- 401 retry via ``on_unauthorized`` (once).
- Error envelope normalization into ``fms_odata_spec.FMODataError`` (and
  subclasses), reusing the spec package's exception hierarchy.

@see https://github.com/fsans/fms-odata-spec/blob/main/docs/04-authentication.md
"""

from __future__ import annotations

import json as _json
import re
from typing import Any, Callable, Dict, Optional, Tuple, Union

import httpx

from fms_odata_spec import (
    FMAuthError,
    FMODataError,
    ODataErrorBody,
    ODataErrorInner,
    RequestRef,
)

from .types import TokenProvider

__all__ = [
    "resolve_auth_header",
    "HttpClientContext",
    "HttpRequestOptions",
    "execute_request",
    "execute_json",
]

#: Schemes that pass through verbatim; bare tokens get ``Bearer `` prefixed.
_AUTH_SCHEME_RE = re.compile(r"^(basic|bearer|negotiate|digest)\s+\S", re.I)

_ACCEPT_DEFAULTS = {
    "json": "application/json",
    "xml": "application/xml",
    "text": "text/plain",
    "binary": "application/octet-stream",
    "none": "*/*",
}


def resolve_auth_header(provider: TokenProvider) -> str:
    """Resolve a :data:`TokenProvider` to a complete Authorization header value.

    Bare strings are prefixed with ``Bearer ``; scheme-prefixed values
    (``Basic``, ``Bearer``, ``Negotiate``, ``Digest``) pass through.
    """
    raw = provider() if callable(provider) else provider
    if not isinstance(raw, str) or len(raw) == 0:
        raise TypeError("fms-odata-py: token resolver produced an empty value")
    return raw if _AUTH_SCHEME_RE.match(raw) else f"Bearer {raw}"


class HttpClientContext:
    """Context supplied by the client to execute a request.

    Carries the token provider, the 401-retry hook, the httpx client, and the
    timeout. Kept as a plain object so the (future) async transport can define
    an analogous context without touching the query/entity layers.
    """

    __slots__ = ("token", "on_unauthorized", "client", "timeout_ms")

    def __init__(
        self,
        *,
        token: TokenProvider,
        on_unauthorized: Optional[Callable[[], None]],
        client: httpx.Client,
        timeout_ms: Optional[int],
    ) -> None:
        self.token = token
        self.on_unauthorized = on_unauthorized
        self.client = client
        self.timeout_ms = timeout_ms


class HttpRequestOptions:
    """Options accepted by the shared request executor.

    Attributes:
        method: HTTP method (default ``GET``).
        headers: Extra headers.
        content: Request body (bytes or str).
        accept: Expected response shape; controls default ``Accept`` header.
    """

    __slots__ = ("method", "headers", "content", "accept")

    def __init__(
        self,
        *,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        content: Optional[Union[bytes, str]] = None,
        accept: str = "json",
    ) -> None:
        self.method = method
        self.headers = headers
        self.content = content
        self.accept = accept


def _build_headers(
    ctx: HttpClientContext, opts: HttpRequestOptions
) -> Dict[str, str]:
    headers: Dict[str, str] = dict(opts.headers) if opts.headers else {}
    headers["Authorization"] = resolve_auth_header(ctx.token)
    # Required by the Claris FMS OData API for all requests.
    headers.setdefault("OData-Version", "4.0")
    headers.setdefault("OData-MaxVersion", "4.0")
    headers.setdefault("Accept", _ACCEPT_DEFAULTS.get(opts.accept, "application/json"))
    return headers


def _timeout(ctx: HttpClientContext) -> Optional[float]:
    if ctx.timeout_ms and ctx.timeout_ms > 0:
        return ctx.timeout_ms / 1000.0
    return None


def execute_request(
    ctx: HttpClientContext, url: str, opts: Optional[HttpRequestOptions] = None
) -> httpx.Response:
    """Execute an HTTP request against the FMS OData endpoint.

    Centralizes auth, timeout, retry, and error handling. Returns the raw
    ``httpx.Response`` on success (2xx). Raises ``FMODataError`` (or subclass)
    on non-2xx.
    """
    return _execute_request_impl(ctx, url, opts or HttpRequestOptions(), retried=False)


def _execute_request_impl(
    ctx: HttpClientContext, url: str, opts: HttpRequestOptions, retried: bool
) -> httpx.Response:
    headers = _build_headers(ctx, opts)
    timeout = _timeout(ctx)
    try:
        res = ctx.client.request(
            opts.method,
            url,
            headers=headers,
            content=opts.content,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise FMODataError(
            f"Request timed out after {ctx.timeout_ms}ms",
            status=0,
            request=RequestRef(method=opts.method, url=url),
        ) from exc
    except httpx.HTTPError as exc:
        raise FMODataError(
            f"Network error: {exc}",
            status=0,
            request=RequestRef(method=opts.method, url=url),
        ) from exc

    if res.status_code == 401 and ctx.on_unauthorized and not retried:
        ctx.on_unauthorized()
        return _execute_request_impl(ctx, url, opts, retried=True)

    if not (200 <= res.status_code < 300):
        raise _parse_error_response(res, url, opts.method)
    return res


def execute_json(
    ctx: HttpClientContext, url: str, opts: Optional[HttpRequestOptions] = None
) -> Any:
    """Execute a request and parse the response as JSON.

    Returns ``None`` on HTTP 204. Tolerates a missing ``content-type: json``
    header by attempting to parse the text body anyway.
    """
    opts = opts or HttpRequestOptions()
    res = execute_request(ctx, url, opts)
    if res.status_code == 204:
        return None
    ctype = (res.headers.get("content-type") or "").lower()
    if "json" not in ctype:
        text = res.text
        if not text:
            return None
        try:
            return _json.loads(text)
        except _json.JSONDecodeError:
            raise FMODataError(
                f'Expected JSON response, got "{ctype or "no content-type"}"',
                status=res.status_code,
                odata_error=text,
                request=RequestRef(method=opts.method, url=url),
            )
    try:
        return res.json()
    except _json.JSONDecodeError as exc:
        raise FMODataError(
            f"Failed to parse JSON response: {exc}",
            status=res.status_code,
            request=RequestRef(method=opts.method, url=url),
        ) from exc


def _parse_error_response(
    res: httpx.Response, url: str, method: str
) -> FMODataError:
    """Parse an error response body into an ``FMODataError`` (or subclass).

    Handles both stock OData JSON envelopes (``{ error: { code, message } }``)
    and FileMaker's XML envelope
    (``<m:error><m:code>212</m:code><m:message>...</m:message></m:error>``).
    Maps 401 -> ``FMAuthError``.
    """
    status = res.status_code
    try:
        body = res.text
    except Exception:
        body = ""

    code: Optional[str] = None
    message = res.reason_phrase or f"HTTP {status}"
    odata_error: Any = body

    ctype = (res.headers.get("content-type") or "").lower()
    looks_json = "json" in ctype or (body.startswith("{") and body.endswith("}"))
    looks_xml = (
        "xml" in ctype
        or body.lstrip().startswith("<?xml")
        or "<m:error" in body
    )

    if looks_json:
        try:
            parsed = _json.loads(body)
            odata_error = parsed
            err = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(err, dict):
                err_code = err.get("code")
                raw_msg = err.get("message")
                msg = (
                    raw_msg
                    if isinstance(raw_msg, str)
                    else (raw_msg.get("value") if isinstance(raw_msg, dict) else None)
                )
                if err_code:
                    code = str(err_code)
                if msg:
                    message = msg
        except _json.JSONDecodeError:
            pass
    elif looks_xml:
        import re as _re

        code_match = _re.search(r"<m:code>([^<]+)</m:code>", body)
        msg_match = _re.search(r"<m:message(?:\s[^>]*)?>([^<]+)</m:message>", body)
        if code_match:
            code = code_match.group(1)
        if msg_match:
            message = msg_match.group(1)

    request = RequestRef(method=method, url=url)

    if status == 401:
        err = FMAuthError(message or "Unauthorized", request=request)
        if code:
            err.code = code
        return err

    return FMODataError(
        message,
        status=status,
        code=code,
        odata_error=odata_error,
        request=request,
    )
