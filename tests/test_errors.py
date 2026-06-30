"""Tests for error parsing.

Ports ``tests/unit/errors.test.ts`` from fms-odata-js. The Python client
reuses the spec-py error hierarchy (``FMODataError``, ``FMAuthError``, etc.)
rather than defining its own; these tests verify the transport's
``_parse_error_response`` correctly normalizes both JSON and XML envelopes.
"""

from __future__ import annotations

import httpx
import pytest

from fms_odata import FMODataError
from fms_odata.http import _parse_error_response

REQ_URL = "https://fms.example.com/fmi/odata/v4/DB/x"


def _req():
    return httpx.Request("GET", "https://example/")


def test_parses_stock_odata_json_envelope():
    res = httpx.Response(
        404,
        headers={"content-type": "application/json"},
        content=b'{"error":{"code":"404","message":"Not Found"}}',
        request=_req(),
    )
    err = _parse_error_response(res, REQ_URL, "GET")
    assert err.status == 404
    assert err.code == "404"
    assert str(err) == "Not Found"
    assert err.request is not None
    assert err.request.url == REQ_URL


def test_parses_json_envelope_with_nested_message_value():
    res = httpx.Response(
        400,
        headers={"content-type": "application/json"},
        content=b'{"error":{"code":"X","message":{"value":"deep"}}}',
        request=_req(),
    )
    err = _parse_error_response(res, REQ_URL, "GET")
    assert err.code == "X"
    assert str(err) == "deep"


def test_parses_filemaker_xml_envelope():
    body = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<m:error xmlns:m="http://docs.oasis-open.org/odata/ns/metadata">'
        b"<m:code>212</m:code>"
        b'<m:message xml:lang="en">(212): Invalid account/password</m:message>'
        b"</m:error>"
    )
    res = httpx.Response(
        401,
        headers={"content-type": "application/xml"},
        content=body,
        request=_req(),
    )
    err = _parse_error_response(res, REQ_URL, "GET")
    assert err.status == 401
    assert err.code == "212"
    assert str(err) == "(212): Invalid account/password"


def test_falls_back_to_reason_phrase_when_body_empty():
    res = httpx.Response(500, text="", request=_req())
    err = _parse_error_response(res, REQ_URL, "GET")
    assert err.status == 500
    # httpx may not populate reason_phrase; message falls back to HTTP {status}
    assert str(err) in ("Server Error", "HTTP 500", "Internal Server Error")


def test_detects_json_xml_from_body_shape_without_content_type():
    json_res = httpx.Response(
        400,
        content=b'{"error":{"code":"Z","message":"zz"}}',
        request=_req(),
    )
    err = _parse_error_response(json_res, REQ_URL, "GET")
    assert err.code == "Z"
    assert str(err) == "zz"

    xml_res = httpx.Response(
        400,
        content=b'<m:error xmlns:m="x"><m:code>99</m:code><m:message>bad</m:message></m:error>',
        request=_req(),
    )
    err2 = _parse_error_response(xml_res, REQ_URL, "GET")
    assert err2.code == "99"
    assert str(err2) == "bad"
