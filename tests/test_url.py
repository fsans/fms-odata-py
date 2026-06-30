"""Tests for URL encoding helpers.

Ports ``tests/unit/url.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fms_odata import (
    build_query_string,
    encode_path_segment,
    escape_string_literal,
    format_date_time,
    format_literal,
    odata_encode,
    parse_date_time,
)


def test_escape_string_literal_doubles_quotes():
    assert escape_string_literal("O'Brien") == "O''Brien"


def test_escape_string_literal_leaves_other_chars():
    assert escape_string_literal("plain text 123 !@#") == "plain text 123 !@#"


def test_escape_string_literal_empty():
    assert escape_string_literal("") == ""


def test_escape_string_literal_only_quotes():
    assert escape_string_literal("'''") == "''''''"


def test_format_date_time_utc_iso_without_millis():
    d = datetime(2026, 4, 17, 14, 45, 30, 123000, tzinfo=timezone.utc)
    assert format_date_time(d) == "2026-04-17T14:45:30Z"


def test_format_date_time_zero_seconds():
    d = datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert format_date_time(d) == "2026-01-01T00:00:00Z"


def test_format_date_time_throws_on_invalid():
    with pytest.raises(TypeError, match="invalid datetime"):
        format_date_time("not-a-date")  # type: ignore[arg-type]


def test_parse_date_time_with_millis():
    d = parse_date_time("2026-04-17T14:45:30.123Z")
    assert d == datetime(2026, 4, 17, 14, 45, 30, 123000, tzinfo=timezone.utc)


def test_parse_date_time_without_millis():
    d = parse_date_time("2026-04-17T14:45:30Z")
    assert d == datetime(2026, 4, 17, 14, 45, 30, tzinfo=timezone.utc)


def test_parse_date_time_throws_on_invalid():
    with pytest.raises(TypeError, match="invalid date string"):
        parse_date_time("not-a-date")


def test_format_literal_string_with_quote_escaping():
    assert format_literal("O'Brien") == "'O''Brien'"


def test_format_literal_integers_floats():
    assert format_literal(0) == "0"
    assert format_literal(42) == "42"
    assert format_literal(-1.5) == "-1.5"


def test_format_literal_booleans_lowercase():
    assert format_literal(True) == "true"
    assert format_literal(False) == "false"


def test_format_literal_date_as_utc_iso():
    d = datetime(2026, 4, 17, 14, 45, 30, 500000, tzinfo=timezone.utc)
    assert format_literal(d) == "2026-04-17T14:45:30Z"


def test_encode_path_segment_spaces_as_pct20():
    assert encode_path_segment("My Layout") == "My%20Layout"


def test_encode_path_segment_other_reserved():
    assert encode_path_segment("O'Brien & Sons") == "O%27Brien%20%26%20Sons"


def test_odata_encode_spaces_as_pct20():
    assert odata_encode("name eq Joe") == "name%20eq%20Joe"


def test_odata_encode_preserves_commas():
    assert odata_encode("ID,Name,Age") == "ID,Name,Age"
    assert odata_encode("name asc,age desc") == "name%20asc,age%20desc"


def test_odata_encode_preserves_dollar_and_equals():
    assert odata_encode("Orders($select=id,total;$top=5)") == "Orders($select=id,total;$top=5)"


def test_odata_encode_encodes_other_special():
    assert odata_encode("name eq 'Joe'") == "name%20eq%20'Joe'"
    assert odata_encode("a & b") == "a%20%26%20b"


def test_build_query_string_joins_pairs():
    assert build_query_string([("$top", "10"), ("$skip", "5")]) == "$top=10&$skip=5"


def test_build_query_string_preserves_key_verbatim():
    assert build_query_string([("$filter", "a eq 1")]) == "$filter=a%20eq%201"


def test_build_query_string_spaces_pct20_not_plus():
    assert build_query_string([("$filter", "name eq 'Joe'")]) == "$filter=name%20eq%20'Joe'"


def test_build_query_string_skips_empty_nullish():
    assert build_query_string([("$top", ""), ("$skip", "0")]) == "$skip=0"


def test_build_query_string_preserves_order():
    assert build_query_string([("$skip", "5"), ("$top", "10")]) == "$skip=5&$top=10"


def test_build_query_string_preserves_commas():
    qs = build_query_string([("$select", "ID,Name,Age"), ("$orderby", "name asc,age desc")])
    assert qs == "$select=ID,Name,Age&$orderby=name%20asc,age%20desc"
    assert "%2C" not in qs
