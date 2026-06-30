"""Tests for $batch serialization and response parsing.

Ports ``tests/unit/batch.test.ts`` from fms-odata-js, adapted to the sync
indexed-responses API (no Promise handles).
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from .conftest import BASE, make_client, text_response


def test_batch_builder_created():
    db = make_client(lambda req: httpx.Response(200, request=req))
    batch = db.batch()
    assert batch is not None
    db.close()


def test_batch_serializes_read_operation():
    db = make_client(lambda req: httpx.Response(200, request=req))
    batch = db.batch()
    batch.add("contact", query={"$top": 5})
    serialized = batch.serialize()
    assert serialized["boundary"].startswith("batch_")
    assert f"GET {BASE}/contact?$top=5" in serialized["body"]
    assert f"--{serialized['boundary']}" in serialized["body"]
    assert f"--{serialized['boundary']}--" in serialized["body"]
    db.close()


def test_batch_serializes_changeset_create():
    db = make_client(lambda req: httpx.Response(200, request=req))
    batch = db.batch()
    batch.changeset(lambda cs: cs.create("contact", {"name": "Alice"}))
    serialized = batch.serialize()
    assert "POST" in serialized["body"]
    assert f"{BASE}/contact" in serialized["body"]
    assert _json.dumps({"name": "Alice"}) in serialized["body"]
    db.close()


def test_batch_send_parses_responses():
    def handler(req):
        # Return a multipart response with two parts.
        boundary = "batch_resp_123"
        part1 = "\r\n".join([
            "Content-Type: application/http",
            "Content-Transfer-Encoding: binary",
            "",
            "HTTP/1.1 201 Created",
            "Content-Type: application/json",
            "",
            _json.dumps({"id": 1, "name": "Alice"}),
        ])
        part2 = "\r\n".join([
            "Content-Type: application/http",
            "Content-Transfer-Encoding: binary",
            "",
            "HTTP/1.1 200 OK",
            "Content-Type: application/json",
            "",
            _json.dumps({"value": [{"id": 1}]}),
        ])
        body = f"--{boundary}\r\n{part1}\r\n--{boundary}\r\n{part2}\r\n--{boundary}--"
        return text_response(body, headers={"content-type": f"multipart/mixed; boundary={boundary}"})

    db = make_client(handler)
    batch = db.batch()
    batch.changeset(lambda cs: cs.create("contact", {"name": "Alice"}))
    batch.add("contact", query={"$top": 1})
    result = batch.send()
    assert len(result.responses) >= 2
    assert all(r.ok for r in result.responses)
    assert result.ok
    db.close()
