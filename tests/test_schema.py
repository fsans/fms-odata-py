"""Tests for schema DDL operations.

Ports ``tests/unit/schema.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from .conftest import BASE, json_response, make_client


def test_create_table_posts_to_filemaker_tables():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content)
        return json_response({"id": 1})

    db = make_client(handler)
    db.create_table(
        {
            "tableName": "Company",
            "fields": [
                {"name": "Company ID", "type": "int", "primary": True},
                {"name": "Company Name", "type": "varchar(100)", "nullable": False},
            ],
        }
    )
    assert captured["url"] == f"{BASE}/FileMaker_Tables"
    assert captured["method"] == "POST"
    assert captured["body"]["tableName"] == "Company"
    db.close()


def test_create_table_requires_table_name():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(TypeError, match="tableName"):
        db.create_table({"fields": [{"name": "x", "type": "int"}]})
    db.close()


def test_create_table_requires_fields():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(TypeError, match="fields"):
        db.create_table({"tableName": "T"})
    db.close()


def test_create_table_validates_field_types():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(TypeError, match="unsupported field type"):
        db.create_table(
            {
                "tableName": "T",
                "fields": [{"name": "x", "type": "bogus_type"}],
            }
        )
    db.close()


def test_delete_table_requires_confirm():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(TypeError, match="confirm=True"):
        db.delete_table("OldTable")
    db.close()


def test_delete_table_with_confirm_issues_delete():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.delete_table("OldTable", confirm=True)
    assert captured["url"] == f"{BASE}/FileMaker_Tables/OldTable"
    assert captured["method"] == "DELETE"
    db.close()


def test_add_fields_patches_table():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content)
        return json_response({})

    db = make_client(handler)
    db.add_fields(
        {
            "tableName": "Company",
            "fields": [{"name": "Phone", "type": "varchar(30)"}],
        }
    )
    assert captured["url"] == f"{BASE}/FileMaker_Tables/Company"
    assert captured["method"] == "PATCH"
    assert captured["body"]["fields"] == [{"name": "Phone", "type": "varchar(30)"}]
    db.close()


def test_create_index_posts_to_filemaker_indexes():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content)
        return json_response({})

    db = make_client(handler)
    db.create_index("Company", "Company Name")
    assert captured["url"] == f"{BASE}/FileMaker_Indexes/Company"
    assert captured["method"] == "POST"
    assert captured["body"] == {"indexName": "Company Name"}
    db.close()


def test_delete_index_issues_delete():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.delete_index("Company", "Company Name")
    assert captured["url"] == f"{BASE}/FileMaker_Indexes/Company/Company%20Name"
    assert captured["method"] == "DELETE"
    db.close()
