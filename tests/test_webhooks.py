"""Tests for webhook management.

Ports ``tests/unit/webhooks.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from .conftest import BASE, json_response, make_client


def test_create_webhook_posts_to_webhook_add():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content)
        return json_response({"id": "abc123"})

    db = make_client(handler)
    db.create_webhook(
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
        return json_response({})

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


def test_remove_webhook_posts_id():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["body"] = _json.loads(req.content)
        return json_response({})

    db = make_client(handler)
    db.remove_webhook("abc123")
    assert captured["url"] == f"{BASE}/Webhook.Remove"
    assert captured["body"] == {"id": "abc123"}
    db.close()


def test_get_all_webhooks_posts_to_getall():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return json_response({"value": []})

    db = make_client(handler)
    db.get_all_webhooks()
    assert captured["url"] == f"{BASE}/Webhook.GetAll"
    db.close()


def test_invoke_webhook_posts_id():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["body"] = _json.loads(req.content)
        return json_response({})

    db = make_client(handler)
    db.invoke_webhook("abc123")
    assert captured["url"] == f"{BASE}/Webhook.Invoke"
    assert captured["body"] == {"id": "abc123"}
    db.close()
