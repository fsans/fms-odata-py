"""Tests for the HTTP transport layer (auth, timeout, 401 retry, errors).

Ports ``tests/unit/http.test.ts`` from fms-odata-js, using httpx.MockTransport
instead of a mocked fetch.
"""

from __future__ import annotations

import httpx
import pytest

from fms_odata import FMSODataClient, FMODataError, FMAuthError
from fms_odata.http import resolve_auth_header
from fms_odata_spec import basic_auth

from .conftest import json_response, make_client


def test_resolve_auth_header_prefixes_bare_tokens():
    assert resolve_auth_header("abc123") == "Bearer abc123"


def test_resolve_auth_header_passes_through_scheme_prefixed():
    assert resolve_auth_header("Basic dXNlcjpwYXNz") == "Basic dXNlcjpwYXNz"
    assert resolve_auth_header("Bearer x.y.z") == "Bearer x.y.z"
    assert resolve_auth_header("FMID zzz") == "FMID zzz"


def test_resolve_auth_header_calls_callable():
    assert resolve_auth_header(lambda: "Basic zzz") == "Basic zzz"


def test_resolve_auth_header_throws_on_empty():
    with pytest.raises(TypeError, match="empty"):
        resolve_auth_header(lambda: "")


def test_basic_auth_base64_encodes():
    assert basic_auth("admin", "wakawaka") == "Basic YWRtaW46d2FrYXdha2E="


def test_basic_auth_handles_utf8():
    import base64

    expected = "Basic " + base64.b64encode("üser:pässword".encode("utf-8")).decode("ascii")
    assert basic_auth("üser", "pässword") == expected


def test_sends_authorization_header_from_token():
    captured = {}

    def handler(req):
        captured["auth"] = req.headers.get("authorization")
        captured["accept"] = req.headers.get("accept")
        return json_response({"value": []})

    db = make_client(handler)
    db.from_("contact").get()
    assert captured["auth"] == "Bearer abc"
    assert captured["accept"] == "application/json"
    db.close()


def test_passes_through_basic_token_without_reprefixing():
    captured = {}

    def handler(req):
        captured["auth"] = req.headers.get("authorization")
        return json_response({"value": []})

    db = make_client(handler, token=basic_auth("admin", "wakawaka"))
    db.from_("contact").get()
    assert captured["auth"].startswith("Basic ")
    db.close()


def test_retries_once_on_401_after_calling_on_unauthorized():
    calls = {"n": 0}
    on_unauthorized_called = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, request=req)
        return json_response({"value": [{"id": 1}]})

    def on_unauthorized():
        on_unauthorized_called["n"] += 1

    db = make_client(handler, on_unauthorized=on_unauthorized)
    result = db.from_("contact").get()
    assert on_unauthorized_called["n"] == 1
    assert calls["n"] == 2
    assert result.value == [{"id": 1}]
    db.close()


def test_does_not_retry_401_without_on_unauthorized():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, request=req)

    db = make_client(handler)
    with pytest.raises(FMAuthError):
        db.from_("contact").get()
    assert calls["n"] == 1
    db.close()


def test_does_not_retry_twice_if_refreshed_request_also_401():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, request=req)

    db = make_client(handler, on_unauthorized=lambda: None)
    with pytest.raises(FMAuthError):
        db.from_("contact").get()
    assert calls["n"] == 2
    db.close()


def test_throws_typed_error_on_http_error():
    def handler(req):
        return json_response(
            {"error": {"code": "400", "message": "Bad stuff"}},
            status=400,
        )

    db = make_client(handler)
    with pytest.raises(FMODataError) as exc_info:
        db.from_("contact").get()
    err = exc_info.value
    assert err.status == 400
    assert err.code == "400"
    assert str(err) == "Bad stuff"
    assert err.request is not None
    assert err.request.url == "https://fms.example.com/fmi/odata/v4/Invoices/contact"
    assert err.request.method == "GET"
    db.close()


def test_times_out_when_timeout_ms_elapses():
    # httpx MockTransport runs handlers synchronously, so real wall-clock
    # timeouts can't be enforced. Instead, simulate the timeout by raising
    # httpx.TimeoutException from the handler (which is what httpx would do
    # on a real network timeout).
    def handler(req):
        raise httpx.TimeoutException("simulated timeout")

    db = make_client(handler, timeout_ms=25)
    with pytest.raises(FMODataError, match="timed out"):
        db.from_("contact").get()
    db.close()
