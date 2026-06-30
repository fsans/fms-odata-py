"""Tests for the fluent query builder URL output.

Ports ``tests/unit/query.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from fms_odata import Filter, Query, filter_factory
from fms_odata.query import _serialize_options

BASE = "https://fms.example.com/fmi/odata/v4/Invoices"


def q(entity_set="Customer"):
    return Query(BASE, entity_set)


def decoded_params(url):
    qs = url.split("?", 1)[1] if "?" in url else ""
    out = {}
    for part in qs.split("&"):
        if not part:
            continue
        eq = part.find("=")
        k = unquote(part[:eq])
        v = unquote(part[eq + 1 :])
        out[k] = v
    return out


# -- Filter factory ---------------------------------------------------------


def test_filter_eq_ne_gt_ge_lt_le():
    f = filter_factory
    assert f.eq("city", "Barcelona").expr == "city eq 'Barcelona'"
    assert f.ne("city", "Girona").expr == "city ne 'Girona'"
    assert f.gt("balance", 0).expr == "balance gt 0"
    assert f.ge("balance", 100).expr == "balance ge 100"
    assert f.lt("balance", 50).expr == "balance lt 50"
    assert f.le("balance", 50).expr == "balance le 50"


def test_filter_escapes_single_quotes():
    assert filter_factory.eq("name", "O'Brien").expr == "name eq 'O''Brien'"


def test_filter_startswith_endswith_contains():
    f = filter_factory
    assert f.startswith("name", "A").expr == "startswith(name,'A')"
    assert f.endswith("name", "Z").expr == "endswith(name,'Z')"
    assert f.contains("name", "O'B").expr == "contains(name,'O''B')"


def test_filter_composes_with_and_or_not_factory():
    f = filter_factory
    a = f.eq("city", "Barcelona")
    b = f.gt("balance", 0)
    assert f.and_(a, b).expr == "(city eq 'Barcelona') and (balance gt 0)"
    assert f.or_(a, b).expr == "(city eq 'Barcelona') or (balance gt 0)"
    assert f.not_(a).expr == "not (city eq 'Barcelona')"


def test_filter_chained_and_or_not():
    expr = filter_factory.eq("city", "Barcelona").and_(filter_factory.gt("balance", 0)).expr
    assert expr == "(city eq 'Barcelona') and (balance gt 0)"
    expr2 = filter_factory.eq("a", 1).or_("b eq 2").not_().expr
    assert expr2 == "not ((a eq 1) or (b eq 2))"


def test_filter_raw_escape_hatch():
    assert filter_factory.raw("startswith(name,'A')").expr == "startswith(name,'A')"


def test_filter_formats_datetime_as_utc_iso_without_millis():
    from datetime import datetime, timezone

    d = datetime(2026, 4, 17, 14, 45, 30, 999000, tzinfo=timezone.utc)
    assert filter_factory.gt("createdAt", d).expr == "createdAt gt 2026-04-17T14:45:30Z"


def test_filter_formats_null_and_boolean():
    assert filter_factory.eq("deletedAt", None).expr == "deletedAt eq null"
    assert filter_factory.eq("active", True).expr == "active eq true"


# -- Query builder URL output -----------------------------------------------


def test_emits_just_entity_set_when_no_options():
    assert q("Customer").to_url() == f"{BASE}/Customer"


def test_percent_encodes_entity_set_names_with_spaces():
    assert q("My Layout").to_url() == f"{BASE}/My%20Layout"


def test_select_joins_fields_with_commas():
    url = q().select("ID", "Name").to_url()
    assert decoded_params(url) == {"$select": "ID,Name"}


def test_select_preserves_literal_commas_not_pct2C():
    url = q().select("ID", "Name", "Age").to_url()
    assert "$select=ID,Name,Age" in url
    assert "%2C" not in url


def test_select_is_cumulative():
    url = q().select("a").select("b", "c").to_url()
    assert decoded_params(url)["$select"] == "a,b,c"


def test_filter_accepts_filter_instance():
    url = q().filter(filter_factory.eq("city", "Barcelona")).to_url()
    assert decoded_params(url)["$filter"] == "city eq 'Barcelona'"


def test_filter_accepts_raw_string():
    url = q().filter("balance gt 0").to_url()
    assert decoded_params(url)["$filter"] == "balance gt 0"


def test_filter_accepts_callback():
    url = q().filter(lambda f: f.eq("city", "Barcelona").and_(f.gt("balance", 0))).to_url()
    assert decoded_params(url)["$filter"] == "(city eq 'Barcelona') and (balance gt 0)"


def test_consecutive_filter_calls_and_together():
    url = q().filter("a eq 1").filter("b eq 2").to_url()
    assert decoded_params(url)["$filter"] == "(a eq 1) and (b eq 2)"


def test_or_after_filter_ors_together():
    url = q().filter("a eq 1").or_(lambda _: "b eq 2").to_url()
    assert decoded_params(url)["$filter"] == "(a eq 1) or (b eq 2)"


def test_orderby_multiple_fields_defaults_asc():
    url = q().orderby("name").orderby("age", "desc").to_url()
    assert decoded_params(url)["$orderby"] == "name asc,age desc"


def test_orderby_preserves_literal_commas():
    url = q().orderby("name").orderby("age", "desc").to_url()
    assert "$orderby=name%20asc,age%20desc" in url
    assert "%2C" not in url


def test_top_skip_count_combined():
    url = q().top(50).skip(10).count().to_url()
    p = decoded_params(url)
    assert p["$top"] == "50"
    assert p["$skip"] == "10"
    assert p["$count"] == "true"


def test_count_false_omits_count():
    url = q().count(False).to_url()
    assert url == f"{BASE}/Customer"


def test_rejects_negative_non_integer_top_skip():
    with pytest.raises(ValueError, match="non-negative"):
        q().top(-1)
    with pytest.raises(ValueError, match="non-negative"):
        q().top(1.5)
    with pytest.raises(ValueError, match="non-negative"):
        q().skip(-1)


def test_search_included_verbatim():
    url = q().search("hello world").to_url()
    assert decoded_params(url)["$search"] == "hello world"


def test_expand_without_nested_options():
    url = q().expand("Orders").to_url()
    assert decoded_params(url)["$expand"] == "Orders"


def test_expand_with_nested_options():
    url = q().expand("Orders", lambda n: n.select("id", "total").top(5)).to_url()
    assert decoded_params(url)["$expand"] == "Orders($select=id,total;$top=5)"


def test_expand_preserves_literal_commas_in_nested_select():
    url = q().expand("Orders", lambda n: n.select("id", "total")).to_url()
    assert "Orders($select=id,total" in url
    assert "%2C" not in url


def test_expand_multiple_navigation_properties():
    url = q().expand("Orders").expand("Contacts", lambda n: n.select("email")).to_url()
    assert decoded_params(url)["$expand"] == "Orders,Contacts($select=email)"


def test_full_query_composition():
    url = (
        q()
        .select("id", "name")
        .filter(lambda f: f.eq("city", "Barcelona").and_(f.gt("balance", 0)))
        .or_(lambda _: "startswith(name,'A')")
        .expand("Orders", lambda n: n.select("id", "total").top(5))
        .orderby("name", "desc")
        .top(50)
        .skip(0)
        .count()
        .to_url()
    )
    p = decoded_params(url)
    assert p == {
        "$select": "id,name",
        "$filter": "((city eq 'Barcelona') and (balance gt 0)) or (startswith(name,'A'))",
        "$expand": "Orders($select=id,total;$top=5)",
        "$orderby": "name desc",
        "$top": "50",
        "$skip": "0",
        "$count": "true",
    }
    assert "+" not in url
    assert "%20" in url


# -- aggregate / groupby ----------------------------------------------------


def test_aggregate_builds_apply():
    url = q().aggregate([{"field": "total", "function": "sum", "alias": "totalSum"}]).to_url()
    assert decoded_params(url)["$apply"] == "aggregate(total with sum as totalSum)"


def test_group_by_with_aggregate():
    url = q().group_by(
        ["customerId"], [{"field": "total", "function": "sum", "alias": "totalSum"}]
    ).to_url()
    assert (
        decoded_params(url)["$apply"]
        == "groupby((customerId),aggregate(total with sum as totalSum))"
    )


def test_group_by_without_aggregate():
    url = q().group_by(["customerId"]).to_url()
    assert decoded_params(url)["$apply"] == "groupby((customerId))"


# -- serialize_options ------------------------------------------------------


def test_serialize_options_empty_returns_empty_string():
    from fms_odata.query import _QueryState

    assert _serialize_options(_QueryState(), top_level=True) == ""
