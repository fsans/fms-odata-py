"""Test helpers: build an FMSODataClient backed by an httpx MockTransport.

Mirrors the ``makeClient(fetchMock)`` pattern from the TS test suite, adapted
to httpx's ``MockTransport`` (the injection seam exposed by the client's
``transport`` option).
"""

from __future__ import annotations

import json as _json
from typing import Callable, Optional

import httpx

from fms_odata import FMSODataClient
from fms_odata_spec import basic_auth

BASE = "https://fms.example.com/fmi/odata/v4/Invoices"


def json_response(body, status=200, headers=None):
    """Build an httpx.Response with a JSON body."""
    h = {"content-type": "application/json"}
    if headers:
        h.update(headers)
    return httpx.Response(
        status,
        headers=h,
        content=_json.dumps(body),
        request=httpx.Request("GET", "https://example/"),
    )


def text_response(body, status=200, headers=None):
    """Build an httpx.Response with a text body."""
    h = {}
    if headers:
        h.update(headers)
    return httpx.Response(
        status,
        headers=h,
        content=body.encode("utf-8") if isinstance(body, str) else body,
        request=httpx.Request("GET", "https://example/"),
    )


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token: str = "abc",
    **kwargs,
) -> FMSODataClient:
    """Build a client whose requests are routed through ``handler``.

    ``handler`` receives the ``httpx.Request`` and returns an ``httpx.Response``.
    """
    transport = httpx.MockTransport(handler)
    return FMSODataClient(
        host="https://fms.example.com",
        database="Invoices",
        token=token,
        transport=transport,
        **kwargs,
    )


def make_basic_client(handler, **kwargs):
    """Client with a Basic auth token (mirrors TS basicAuth usage)."""
    return make_client(handler, token=basic_auth("admin", "wakawaka"), **kwargs)
