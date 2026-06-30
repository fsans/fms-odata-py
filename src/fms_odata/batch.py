"""$batch multipart composer and response parser.

Mirrors ``src/batch.ts`` in fms-odata-js. OData $batch allows multiple
operations in a single HTTP round-trip. A batch consists of read operations
(GET) at the top level and changesets (atomic groups of writes: POST, PATCH,
DELETE).

FMS endpoint: ``POST /fmi/odata/v4/{db}/$batch``
Content-Type: ``multipart/mixed; boundary=batch_<uuid>``

.. note::

   Sync API difference from TS: the TS ``BatchHandle`` is a Promise-backed
   handle resolved after ``batch.send()``. In sync Python there is no Promise
   equivalent; :meth:`Batch.send` returns a :class:`BatchResult` with an
   ordered ``responses`` list that callers index into directly (zipped
   against the original request order).

Known FMS limitations (per fms-odata-js source, tested against FMS 21.x):

1. GET operations must NOT appear before a changeset.
2. Multiple consecutive GET operations drop the last response.
3. POST/PATCH within a changeset requires an explicit Content-Length header
   on the inner HTTP request.
"""

from __future__ import annotations

import json as _json
import re
import uuid
from typing import Any, Dict, List, Optional, Union

import httpx

from .http import HttpRequestOptions, execute_request
from .url import ODataLiteral, encode_path_segment, odata_encode

__all__ = ["Batch", "Changeset", "BatchResult", "BatchOpResult", "BatchReadOp"]


def _utf8_byte_length(s: str) -> int:
    return len(s.encode("utf-8"))


def _generate_boundary(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def _build_entity_set_path(base_url: str, entity_set: str, query: Optional[Dict[str, Any]] = None) -> str:
    parts: List[str] = []
    if query:
        if query.get("$top") is not None:
            parts.append(f"$top={odata_encode(str(query['$top']))}")
        if query.get("$skip") is not None:
            parts.append(f"$skip={odata_encode(str(query['$skip']))}")
        if query.get("$filter"):
            parts.append(f"$filter={odata_encode(query['$filter'])}")
        if query.get("$select"):
            parts.append(f"$select={odata_encode(query['$select'])}")
    qs = "&".join(parts)
    encoded = encode_path_segment(entity_set)
    return f"{base_url}/{encoded}?{qs}" if qs else f"{base_url}/{encoded}"


def _format_key(key: Union[str, int, bool]) -> str:
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, str):
        return f"'{key.replace(chr(39), chr(39)+chr(39))}'"
    raise TypeError("Batch: unsupported key type")


def _build_entity_path(base_url: str, entity_set: str, key: ODataLiteral) -> str:
    return f"{base_url}/{encode_path_segment(entity_set)}({_format_key(key)})"


class BatchOpResult:
    """Result of a single batch operation."""

    __slots__ = ("status", "body", "headers", "ok")

    def __init__(self, status: int, body: Any, headers: Dict[str, str], ok: bool) -> None:
        self.status = status
        self.body = body
        self.headers = headers
        self.ok = ok

    def __repr__(self) -> str:
        return f"BatchOpResult(status={self.status}, ok={self.ok})"


class BatchResult:
    """Result of executing a batch.

    Attributes:
        responses: All responses in request order.
        ok: True if all responses have status < 400.
    """

    __slots__ = ("responses", "ok")

    def __init__(self, responses: List[BatchOpResult], ok: bool) -> None:
        self.responses = responses
        self.ok = ok

    def __repr__(self) -> str:
        return f"BatchResult(ok={self.ok}, {len(self.responses)} responses)"


class _ChangesetOp:
    __slots__ = ("method", "path", "headers", "body")

    def __init__(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
    ) -> None:
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body


class Changeset:
    """Builder for atomic write operations within a batch."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._ops: List[_ChangesetOp] = []

    @property
    def operations(self) -> List[_ChangesetOp]:
        return self._ops

    def create(self, entity_set: str, body: Dict[str, Any]) -> int:
        """Queue a POST. Returns the op index."""
        path = _build_entity_set_path(self._base_url, entity_set)
        self._ops.append(
            _ChangesetOp(
                method="POST",
                path=path,
                headers={"Content-Type": "application/json"},
                body=_json.dumps(body),
            )
        )
        return len(self._ops) - 1

    def patch(
        self,
        entity_set: str,
        key: ODataLiteral,
        body: Dict[str, Any],
        if_match: Optional[str] = None,
    ) -> int:
        """Queue a PATCH. Returns the op index."""
        path = _build_entity_path(self._base_url, entity_set, key)
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if if_match:
            headers["If-Match"] = if_match
        self._ops.append(
            _ChangesetOp(method="PATCH", path=path, headers=headers, body=_json.dumps(body))
        )
        return len(self._ops) - 1

    def delete(
        self,
        entity_set: str,
        key: ODataLiteral,
        if_match: Optional[str] = None,
    ) -> int:
        """Queue a DELETE. Returns the op index."""
        path = _build_entity_path(self._base_url, entity_set, key)
        headers: Dict[str, str] = {}
        if if_match:
            headers["If-Match"] = if_match
        self._ops.append(_ChangesetOp(method="DELETE", path=path, headers=headers))
        return len(self._ops) - 1


class BatchReadOp:
    """Input for a read operation (GET) in a batch."""

    __slots__ = ("entity_set", "query")

    def __init__(self, entity_set: str, query: Optional[Dict[str, Any]] = None) -> None:
        self.entity_set = entity_set
        self.query = query


class Batch:
    """$batch builder.

    Read operations (``add``) are executed independently. Write operations
    (``changeset``) are grouped atomically -- all succeed or all fail.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._reads: List[BatchReadOp] = []
        self._changesets: List[Changeset] = []

    def add(self, entity_set: str, query: Optional[Dict[str, Any]] = None) -> int:
        """Add a read (GET) operation. Returns the read index."""
        self._reads.append(BatchReadOp(entity_set, query))
        return len(self._reads) - 1

    def changeset(self, build: Optional[Any] = None) -> Changeset:
        """Add a changeset. Pass a callback that mutates the :class:`Changeset`,
        or call methods on the returned object directly."""
        cs = Changeset(self._client.base_url)
        if build is not None:
            build(cs)
        self._changesets.append(cs)
        return cs

    def serialize(self) -> Dict[str, str]:
        """Serialize the batch into a multipart body. Returns boundary + body."""
        boundary = _generate_boundary("batch")
        lines: List[str] = []

        # Changesets first (FMS limitation: GETs must not precede a changeset).
        for cs in self._changesets:
            cs_boundary = _generate_boundary("changeset")
            lines.append(f"--{boundary}")
            lines.append(
                f"Content-Type: multipart/mixed; boundary={cs_boundary}"
            )
            lines.append("")
            for op in cs.operations:
                lines.append(f"--{cs_boundary}")
                lines.append("Content-Type: application/http")
                lines.append("Content-Transfer-Encoding: binary")
                lines.append("")
                lines.append(f"{op.method} {op.path} HTTP/1.1")
                if op.headers:
                    for k, v in op.headers.items():
                        lines.append(f"{k}: {v}")
                if op.body is not None:
                    lines.append(f"Content-Length: {_utf8_byte_length(op.body)}")
                    lines.append("")
                    lines.append(op.body)
                else:
                    lines.append("Content-Length: 0")
                    lines.append("")
                    lines.append("")
            lines.append(f"--{cs_boundary}--")

        # Reads (at most one is reliable per FMS limitations).
        for read in self._reads:
            path = _build_entity_set_path(self._client.base_url, read.entity_set, read.query)
            lines.append(f"--{boundary}")
            lines.append("Content-Type: application/http")
            lines.append("Content-Transfer-Encoding: binary")
            lines.append("")
            lines.append(f"GET {path} HTTP/1.1")
            lines.append("Accept: application/json")
            lines.append("")

        lines.append(f"--{boundary}--")
        body = "\r\n".join(lines)
        return {"boundary": boundary, "body": body}

    def send(self) -> BatchResult:
        """Execute the batch and return a :class:`BatchResult`.

        Responses are ordered: changeset ops first (in changeset order), then
        reads (in add order).
        """
        serialized = self.serialize()
        boundary = serialized["boundary"]
        body = serialized["body"]
        res = execute_request(
            self._client._ctx,
            f"{self._client.base_url}/$batch",
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": f"multipart/mixed; boundary={boundary}"},
                content=body,
                accept="none",
            ),
        )
        # The response uses its own boundary (declared in its Content-Type
        # header), which differs from the request boundary.
        resp_boundary = _extract_boundary(res.headers.get("content-type", "")) or boundary
        return _parse_batch_response(res.text, resp_boundary)


def _extract_boundary(content_type: str) -> Optional[str]:
    """Extract the boundary parameter from a multipart Content-Type header."""
    m = re.search(r"boundary=([^;\s]+)", content_type, re.I)
    return m.group(1) if m else None


def _parse_batch_response(text: str, boundary: str) -> BatchResult:
    """Parse a multipart/mixed batch response into a :class:`BatchResult."""
    results: List[BatchOpResult] = []
    # Split on the batch boundary.
    parts = re.split(rf"--{re.escape(boundary)}(?:--|\r?\n)", text)
    for part in parts:
        part = part.strip()
        if not part or part.startswith("Content-Type: multipart/mixed"):
            # Skip preamble and nested changeset wrappers; parse their inner parts too.
            inner_parts = re.split(r"--changeset_[^\r\n]+(?:--|\r?\n)", part)
            for inner in inner_parts:
                inner = inner.strip()
                if inner:
                    parsed = _parse_http_part(inner)
                    if parsed is not None:
                        results.append(parsed)
            continue
        parsed = _parse_http_part(part)
        if parsed is not None:
            results.append(parsed)
    ok = all(r.ok for r in results) if results else True
    return BatchResult(responses=results, ok=ok)


def _parse_http_part(part: str) -> Optional[BatchOpResult]:
    """Parse a single application/http part into a :class:`BatchOpResult`.

    A part may have MIME headers (Content-Type, Content-Transfer-Encoding)
    before the embedded HTTP response. We skip those to find the
    ``HTTP/1.1 <status>`` line.
    """
    lines = part.split("\r\n")
    if not lines:
        return None
    # Find the HTTP status line (skip MIME headers + blank line).
    http_start = 0
    for i, line in enumerate(lines):
        if re.match(r"HTTP/\d\.\d\s+\d+", line.strip()):
            http_start = i
            break
    else:
        return None
    status_match = re.match(r"HTTP/\d\.\d\s+(\d+)\s*(.*)", lines[http_start].strip())
    if not status_match:
        return None
    status = int(status_match.group(1))
    headers: Dict[str, str] = {}
    body_start = http_start + 1
    for i in range(http_start + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            body_start = i + 1
            break
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip()] = v.strip()
    body_text = "\r\n".join(lines[body_start:]).strip()
    body: Any = body_text
    ctype = headers.get("Content-Type", "")
    if "json" in ctype.lower() and body_text:
        try:
            body = _json.loads(body_text)
        except _json.JSONDecodeError:
            pass
    return BatchOpResult(status=status, body=body, headers=headers, ok=status < 400)
