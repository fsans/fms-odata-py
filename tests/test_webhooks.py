"""Tests for webhook management.

Ports ``tests/unit/webhooks.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from .conftest import BASE, json_response, make_client


def test_create_webhook_posts_to_webhook_add_and_returns_id():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content)
        return json_response({"webhookResult": {"webhookID": 42}})

    db = make_client(handler)
    result = db.create_webhook(
        {
            "webhook": "https://my.example.com:8080/webhook",
            "tableName": "contact",
            "select": "id,first_name",
            "filter": "status eq 'active'",
            "notifySchemaChanges": True,
        }
    )
    assert captured["url"] == f"{BASE}/Webhook.Add"
    assert captured["method"] == "POST"
    assert captured["body"]["webhook"] == "https://my.example.com:8080/webhook"
    assert captured["body"]["tableName"] == "contact"
    assert result == {"id": "42"}
    db.close()


def test_create_webhook_accepts_alternate_response_shapes():
    db = make_client(lambda req: json_response({"webhookID": 7}))
    result = db.create_webhook({"webhook": "https://x", "tableName": "t"})
    assert result == {"id": "7"}
    db.close()


def test_create_webhook_throws_when_response_lacks_id():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(RuntimeError, match="webhook id"):
        db.create_webhook({"webhook": "https://x", "tableName": "t"})
    db.close()


def test_create_webhook_requires_webhook_url():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(TypeError, match="webhook"):
        db.create_webhook({"tableName": "contact"})
    db.close()


def test_create_webhook_requires_table_name():
    db = make_client(lambda req: json_response({}))
    with pytest.raises(TypeError, match="tableName"):
        db.create_webhook({"webhook": "https://x"})
    db.close()


def test_create_webhook_merges_legacy_headers_into_endpoint_headers():
    captured = {}

    def handler(req):
        captured["body"] = _json.loads(req.content)
        return json_response({"webhookResult": {"webhookID": 1}})

    db = make_client(handler)
    db.create_webhook(
        {
            "webhook": "https://x",
            "tableName": "contact",
            "headers": {"X-Custom": "val"},
        }
    )
    assert captured["body"]["endpointHeaders"] == {"X-Custom": "val"}
    db.close()


def test_remove_webhook_posts_to_delete_with_id_in_path():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        return json_response({})

    db = make_client(handler)
    db.remove_webhook("1")
    assert captured["url"] == f"{BASE}/Webhook.Delete(1)"
    assert captured["method"] == "POST"
    db.close()


def test_remove_webhook_accepts_numeric_ids():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return json_response({})

    db = make_client(handler)
    db.remove_webhook(42)
    assert captured["url"] == f"{BASE}/Webhook.Delete(42)"
    db.close()


def test_delete_webhook_is_alias_for_remove():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return json_response({})

    db = make_client(handler)
    db.delete_webhook("5")
    assert captured["url"] == f"{BASE}/Webhook.Delete(5)"
    db.close()


def test_get_webhook_gets_with_id_in_path():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        return json_response({"webhook": {"webhookID": 1, "webhook": "https://x", "tableName": "t"}})

    db = make_client(handler)
    result = db.get_webhook("1")
    assert captured["url"] == f"{BASE}/Webhook.Get(1)"
    assert captured["method"] == "GET"
    assert result is not None
    db.close()


def test_get_all_webhooks_gets_getall():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        return json_response({"webhooks": [{"webhookID": 1}]})

    db = make_client(handler)
    db.get_all_webhooks()
    assert captured["url"] == f"{BASE}/Webhook.GetAll"
    assert captured["method"] == "GET"
    db.close()


def test_invoke_webhook_posts_to_invoke_with_id_in_path_and_empty_rowids():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content)
        return json_response({})

    db = make_client(handler)
    db.invoke_webhook("1")
    assert captured["url"] == f"{BASE}/Webhook.Invoke(1)"
    assert captured["method"] == "POST"
    assert captured["body"] == {"rowIDs": []}
    db.close()


def test_invoke_webhook_includes_rowids_when_provided():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["body"] = _json.loads(req.content)
        return json_response({})

    db = make_client(handler)
    db.invoke_webhook("1", row_ids=[10, 20])
    assert captured["url"] == f"{BASE}/Webhook.Invoke(1)"
    assert captured["body"] == {"rowIDs": [10, 20]}
    db.close()
