"""OData URL encoding helpers.

Reuses :func:`fms_odata_spec.escape_string_literal` and
:func:`fms_odata_spec.format_literal` from the spec package (single source of
truth for literal formatting). Keeps the richer, FMS-quirk-aware
``odata_encode`` / ``build_query_string`` / ``encode_path_segment`` /
``format_date_time`` / ``parse_date_time`` helpers locally, mirroring
``src/url.ts`` in fms-odata-js.

Key FileMaker quirks encoded here (see fms-odata-spec docs/13-quirks.md):

- Spaces become ``%20`` (not ``+``) -- required by OData ``$filter``.
- Commas stay literal (not ``%2C``) -- required by ``$select``, ``$orderby``,
  ``$expand``.
- Parentheses stay literal -- required by ``$apply`` expressions.
- ``$``, ``=``, ``;`` stay literal -- required for nested ``$expand`` options.
  FileMaker Server rejects percent-encoded forms of these characters.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple, Union

from fms_odata_spec import escape_string_literal, format_literal

__all__ = [
    "ODataLiteral",
    "escape_string_literal",
    "format_literal",
    "format_date_time",
    "parse_date_time",
    "encode_path_segment",
    "odata_encode",
    "build_query_string",
]

#: Any value that can appear on the right-hand side of an OData ``$filter``
#: comparison. ``datetime`` replaces the TS ``Date``.
ODataLiteral = Union[str, int, float, bool, datetime, None]


def format_date_time(d: datetime) -> str:
    """Format a ``datetime`` as UTC ISO-8601 without milliseconds.

    Mirrors ``formatDateTime`` in fms-odata-js: ``2026-04-17T14:45:30Z``.
    Naive datetimes are assumed to be UTC.
    """
    if not isinstance(d, datetime):
        raise TypeError("format_date_time: invalid datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    iso = d.astimezone(timezone.utc).isoformat()
    # Strip microseconds: "...14:45:30.123000+00:00" -> "...14:45:30+00:00"
    if "." in iso:
        head, rest = iso.split(".", 1)
        tz = ""
        for sep in ("+", "-"):
            idx = rest.find(sep)
            if idx != -1:
                tz = rest[idx:]
                break
        iso = head + tz
    # Replace trailing +00:00 with Z for parity with TS toISOString().
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return iso


def parse_date_time(s: str) -> datetime:
    """Parse an OData DateTimeOffset string (with or without milliseconds)."""
    try:
        # Handle the trailing 'Z' that fromisoformat doesn't accept on 3.9-3.10.
        cleaned = s.replace("Z", "+00:00") if s.endswith("Z") else s
        return datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise TypeError(f"parse_date_time: invalid date string: {s}") from exc


def encode_path_segment(s: str) -> str:
    """Encode a single URL path segment (spaces become ``%20``)."""
    from urllib.parse import quote

    return quote(s, safe="")


def odata_encode(v: str) -> str:
    """Encode an OData query-string value.

    - Spaces become ``%20`` (not ``+``) -- required by OData ``$filter``.
    - Commas stay literal (not ``%2C``) -- required by ``$select``, ``$orderby``,
      ``$expand``.
    - Parentheses stay literal -- required by ``$apply`` expressions.
    - ``$``, ``=``, ``;`` stay literal -- required for nested ``$expand`` options.
    - Apostrophes stay literal (RFC 3986 sub-delim, like JS encodeURIComponent).
    """
    from urllib.parse import quote

    return (
        quote(v, safe="'")
        .replace("%2C", ",")
        .replace("%24", "$")
        .replace("%3D", "=")
        .replace("%3B", ";")
        .replace("%28", "(")
        .replace("%29", ")")
    )


def build_query_string(params: List[Tuple[str, str]]) -> str:
    """Build a querystring from ordered ``[key, value]`` pairs.

    Keys are emitted verbatim (always safe ASCII such as ``$filter``). Values
    are percent-encoded via :func:`odata_encode`. Empty / ``None`` values are
    skipped.
    """
    parts: List[str] = []
    for k, v in params:
        if v is None or v == "":
            continue
        parts.append(f"{k}={odata_encode(v)}")
    return "&".join(parts)
