"""Tests for script invocation.

Ports ``tests/unit/scripts.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from fms_odata import FMScriptError

from .conftest import BASE, json_response, make_client


def test_script_database_scope_no_body_when_parameter_omitted():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = req.content
        captured["content_type"] = req.headers.get("content-type")
        return json_response({"scriptResult": "pong", "scriptError": "0"})

    db = make_client(handler)
    result = db.script("Ping")
    assert result.result_parameter == "pong"
    assert captured["url"] == f"{BASE}/Script.Ping"
    assert captured["method"] == "POST"
    assert captured["body"] in (b"", None)
    assert captured["content_type"] is None
    db.close()


def test_script_sends_script_parameter_value_as_json():
    captured = {}

    def handler(req):
        captured["body"] = req.content.decode()
        captured["content_type"] = req.headers.get("content-type")
        return json_response({"scriptResult": "pong:hi", "scriptError": "0"})

    db = make_client(handler)
    db.script("Ping", parameter="hi")
    assert _json.loads(captured["body"]) == {"scriptParameterValue": "hi"}
    assert captured["content_type"] == "application/json"
    db.close()


def test_script_non_zero_error_raises_fm_script_error():
    def handler(req):
        return json_response({"scriptResult": "", "scriptError": "101"})

    db = make_client(handler)
    with pytest.raises(FMScriptError) as exc_info:
        db.script("Bad")
    assert exc_info.value.script_error == 101
    db.close()


def test_script_nested_envelope_v26():
    def handler(req):
        return json_response(
            {"scriptResult": {"code": 0, "resultParameter": "Hello World"}}
        )

    db = make_client(handler)
    result = db.script("Ping")
    assert result.code == 0
    assert result.result_parameter == "Hello World"
    db.close()


def test_script_nested_envelope_non_zero_raises():
    def handler(req):
        return json_response({"scriptResult": {"code": 3, "resultParameter": ""}})

    db = make_client(handler)
    with pytest.raises(FMScriptError) as exc_info:
        db.script("Bad")
    assert exc_info.value.script_error == 3
    db.close()


def test_script_by_id_builds_fmsid_url():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return json_response({"scriptResult": {"code": 0, "resultParameter": "ok"}})

    db = make_client(handler)
    db.script_by_id(42, parameter="hi")
    assert captured["url"] == f"{BASE}/Script.FMSID:42"
    db.close()


def test_script_entity_set_scope():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return json_response({"scriptResult": {"code": 0, "resultParameter": "ok"}})

    db = make_client(handler)
    db.from_("contact").script("Ping")
    assert captured["url"] == f"{BASE}/contact/Script.Ping"
    db.close()


def test_script_record_scope():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return json_response({"scriptResult": {"code": 0, "resultParameter": "ok"}})

    db = make_client(handler)
    db.from_("contact").by_key(7).script("Ping")
    assert captured["url"] == f"{BASE}/contact(7)/Script.Ping"
    db.close()
