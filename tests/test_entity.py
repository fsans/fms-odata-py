"""Tests for EntityRef CRUD and Query.get/create.

Ports ``tests/unit/entity.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from fms_odata import EntityRef, FMSODataClient

from .conftest import BASE, json_response, make_client


def test_entity_ref_numeric_key_no_quotes():
    db = make_client(lambda req: json_response({}))
    assert db.from_("contact").by_key(123).to_url() == f"{BASE}/contact(123)"
    db.close()


def test_entity_ref_string_key_quotes_and_escapes():
    db = make_client(lambda req: json_response({}))
    assert db.from_("contact").by_key("O'B-1").to_url() == f"{BASE}/contact('O''B-1')"
    db.close()


def test_entity_ref_percent_encodes_entity_set_with_spaces():
    db = make_client(lambda req: json_response({}))
    assert db.from_("My Layout").by_key(5).to_url() == f"{BASE}/My%20Layout(5)"
    db.close()


def test_entity_ref_get_returns_parsed_row():
    def handler(req):
        assert str(req.url) == f"{BASE}/contact(7)"
        assert req.method == "GET"
        return json_response({"id": 7, "name": "Alice"})

    db = make_client(handler)
    row = db.from_("contact").by_key(7).get()
    assert row == {"id": 7, "name": "Alice"}
    db.close()


def test_entity_ref_field_value_unwraps_value():
    def handler(req):
        assert str(req.url) == f"{BASE}/contact(7)/first_name"
        return json_response({"value": "Alice"})

    db = make_client(handler)
    v = db.from_("contact").by_key(7).field_value("first_name")
    assert v == "Alice"
    db.close()


def test_entity_ref_field_value_percent_encodes_field_names_with_spaces():
    def handler(req):
        assert str(req.url) == f"{BASE}/contact(7)/Total%20Hours"
        return json_response({"value": 42})

    db = make_client(handler)
    v = db.from_("contact").by_key(7).field_value("Total Hours")
    assert v == 42
    db.close()


def test_entity_ref_field_value_returns_none_when_null():
    db = make_client(lambda req: json_response({"value": None}))
    v = db.from_("contact").by_key(7).field_value("middle_name")
    assert v is None
    db.close()


def test_entity_ref_patch_default_return_minimal():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = req.content.decode()
        captured["prefer"] = req.headers.get("prefer")
        captured["content_type"] = req.headers.get("content-type")
        return httpx.Response(204, request=req)

    db = make_client(handler)
    result = db.from_("contact").by_key(7).patch({"city": "Girona"})
    assert result is None
    assert captured["url"] == f"{BASE}/contact(7)"
    assert captured["method"] == "PATCH"
    assert _json.loads(captured["body"]) == {"city": "Girona"}
    assert captured["prefer"] == "return=minimal"
    assert captured["content_type"] == "application/json"
    db.close()


def test_entity_ref_patch_return_representation():
    def handler(req):
        assert req.headers.get("prefer") == "return=representation"
        return json_response({"id": 7, "city": "Girona"})

    db = make_client(handler)
    from fms_odata import EntityWriteOptions

    updated = db.from_("contact").by_key(7).patch(
        {"city": "Girona"}, EntityWriteOptions(return_representation=True)
    )
    assert updated == {"id": 7, "city": "Girona"}
    db.close()


def test_entity_ref_patch_forwards_if_match():
    captured = {}

    def handler(req):
        captured["if_match"] = req.headers.get("if-match")
        return httpx.Response(204, request=req)

    db = make_client(handler)
    from fms_odata import EntityWriteOptions

    db.from_("contact").by_key(7).patch({"x": 1}, EntityWriteOptions(if_match='W/"etag-1"'))
    assert captured["if_match"] == 'W/"etag-1"'
    db.close()


def test_entity_ref_delete_issues_delete():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.from_("contact").by_key(7).delete()
    assert captured["url"] == f"{BASE}/contact(7)"
    assert captured["method"] == "DELETE"
    db.close()


def test_entity_ref_delete_forwards_if_match():
    captured = {}

    def handler(req):
        captured["if_match"] = req.headers.get("if-match")
        return httpx.Response(204, request=req)

    db = make_client(handler)
    from fms_odata import EntityWriteOptions

    db.from_("contact").by_key(7).delete(EntityWriteOptions(if_match='W/"etag-9"'))
    assert captured["if_match"] == 'W/"etag-9"'
    db.close()


def test_query_create_posts_body_returns_echoed_row():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = req.content.decode()
        return json_response({"id": 99, "name": "Acme"})

    db = make_client(handler)
    row = db.from_("contact").create({"name": "Acme"})
    assert row == {"id": 99, "name": "Acme"}
    assert captured["url"] == f"{BASE}/contact"
    assert captured["method"] == "POST"
    assert _json.loads(captured["body"]) == {"name": "Acme"}
    db.close()


def test_query_get_returns_value_count_next_link():
    def handler(req):
        return json_response(
            {
                "value": [{"id": 1}, {"id": 2}],
                "@odata.count": 17,
                "@odata.nextLink": "https://fms.example.com/next",
            }
        )

    db = make_client(handler)
    result = db.from_("contact").top(2).count().get()
    assert len(result.value) == 2
    assert result.count == 17
    assert result.next_link == "https://fms.example.com/next"
    db.close()


def test_query_get_defaults_empty_value_when_omitted():
    db = make_client(lambda req: json_response({}))
    result = db.from_("contact").get()
    assert result.value == []
    assert result.count is None
    assert result.next_link is None
    db.close()


# -- $ref operations --------------------------------------------------------


def test_get_refs_returns_array_from_collection_nav():
    def handler(req):
        assert str(req.url) == f"{BASE}/contact(7)/addresses/$ref"
        return json_response(
            {"value": [{"@odata.id": f"{BASE}/address(1)"}, {"@odata.id": f"{BASE}/address(2)"}]}
        )

    db = make_client(handler)
    refs = db.from_("contact").by_key(7).get_refs("addresses")
    assert len(refs) == 2
    assert refs[0]["@odata.id"] == f"{BASE}/address(1)"
    db.close()


def test_get_refs_handles_single_valued_nav():
    def handler(req):
        return json_response({"@odata.id": f"{BASE}/address(1)"})

    db = make_client(handler)
    refs = db.from_("contact").by_key(7).get_refs("primary_address")
    assert len(refs) == 1
    assert refs[0]["@odata.id"] == f"{BASE}/address(1)"
    db.close()


def test_add_ref_posts_target_url():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = req.content.decode()
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.from_("contact").by_key(7).add_ref("addresses", f"{BASE}/address(5)")
    assert captured["url"] == f"{BASE}/contact(7)/addresses/$ref"
    assert captured["method"] == "POST"
    assert _json.loads(captured["body"]) == {"@odata.id": f"{BASE}/address(5)"}
    db.close()
