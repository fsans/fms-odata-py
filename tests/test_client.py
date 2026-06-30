"""Tests for FMSODataClient construction and base URL derivation.

Ports the behavioral coverage of ``tests/unit/client.test.ts`` (M1 scaffold
section) from fms-odata-js.
"""

from __future__ import annotations

import httpx
import pytest

from fms_odata import FMSODataClient, Query
from fms_odata_spec import basic_auth

from .conftest import make_client


def test_constructs_with_minimal_options_and_derives_base_url():
    db = FMSODataClient(host="https://fms.example.com", database="Invoices", token="xxx")
    assert db.base_url == "https://fms.example.com/fmi/odata/v4/Invoices"
    db.close()


def test_strips_trailing_slashes_from_host():
    db = FMSODataClient(host="https://fms.example.com/", database="Invoices", token="xxx")
    assert db.base_url == "https://fms.example.com/fmi/odata/v4/Invoices"
    db.close()


def test_throws_when_host_missing():
    with pytest.raises(TypeError, match="host"):
        FMSODataClient(database="X", token="t")


def test_throws_when_database_missing():
    with pytest.raises(TypeError, match="database"):
        FMSODataClient(host="https://x", token="t")


def test_throws_when_token_missing():
    with pytest.raises(TypeError, match="token"):
        FMSODataClient(host="https://x", database="X", token=None)


def test_from_returns_query():
    db = FMSODataClient(host="https://fms.example.com", database="Invoices", token="xxx")
    q = db.from_("Customer")
    assert isinstance(q, Query)
    assert q.to_url() == "https://fms.example.com/fmi/odata/v4/Invoices/Customer"
    db.close()


def test_from_throws_when_entity_set_empty():
    db = FMSODataClient(host="https://fms.example.com", database="Invoices", token="xxx")
    with pytest.raises(TypeError, match="entity_set"):
        db.from_("")
    db.close()


def test_url_encodes_database_name_in_base_url():
    db = FMSODataClient(host="https://fms.example.com", database="My Invoices", token="xxx")
    assert db.base_url == "https://fms.example.com/fmi/odata/v4/My%20Invoices"
    db.close()


def test_context_manager_closes_client():
    with FMSODataClient(host="https://fms.example.com", database="X", token="t") as db:
        assert db.base_url.endswith("/X")
    # Client should be closed after exiting.
