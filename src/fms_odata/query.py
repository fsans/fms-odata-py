"""Fluent OData query builder.

Mirrors ``src/query.ts`` in fms-odata-js. ``Query`` accumulates ``$select``,
``$filter``, ``$expand``, ``$orderby``, ``$top``, ``$skip``, ``$count``,
``$search``, and ``$apply`` options and serializes them into an absolute URL
via :meth:`Query.to_url`. HTTP execution (``.get()``) delegates to the
transport layer in :mod:`fms_odata.http`.

This module is pure data + URL building -- no I/O leakage -- so the planned
``AsyncFMSODataClient`` can reuse it without modification.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from fms_odata_spec import AggregateFunction

from .entity import EntityRef
from .http import HttpRequestOptions, execute_json
from .url import ODataLiteral, build_query_string, encode_path_segment, format_literal

__all__ = [
    "Filter",
    "FilterFactory",
    "filter_factory",
    "FilterInput",
    "OrderDir",
    "QueryResult",
    "Query",
]


class Filter:
    """Opaque filter expression produced by :data:`filter_factory`.

    Compose with :meth:`and_`, :meth:`or_`, :meth:`not_`. Pass to
    :meth:`Query.filter`.
    """

    __slots__ = ("expr",)

    def __init__(self, expr: str) -> None:
        self.expr = expr

    def __str__(self) -> str:
        return self.expr

    def __repr__(self) -> str:
        return f"Filter({self.expr!r})"

    def and_(self, other: Union["Filter", str]) -> "Filter":
        return Filter(f"({self.expr}) and ({_coerce(other)})")

    def or_(self, other: Union["Filter", str]) -> "Filter":
        return Filter(f"({self.expr}) or ({_coerce(other)})")

    def not_(self) -> "Filter":
        return Filter(f"not ({self.expr})")


def _coerce(x: Union[Filter, str]) -> str:
    return x.expr if isinstance(x, Filter) else x


class FilterFactory:
    """Factory passed to callback-form :meth:`Query.filter`.

    Methods mirror ``filterFactory`` in fms-odata-js. ``and_``/``or_``/``not_``
    use trailing underscores to avoid shadowing Python keywords/builtins.
    """

    def eq(self, field: str, value: ODataLiteral) -> Filter:
        return Filter(f"{field} eq {format_literal(_to_literal(value))}")

    def ne(self, field: str, value: ODataLiteral) -> Filter:
        return Filter(f"{field} ne {format_literal(_to_literal(value))}")

    def gt(self, field: str, value: ODataLiteral) -> Filter:
        return Filter(f"{field} gt {format_literal(_to_literal(value))}")

    def ge(self, field: str, value: ODataLiteral) -> Filter:
        return Filter(f"{field} ge {format_literal(_to_literal(value))}")

    def lt(self, field: str, value: ODataLiteral) -> Filter:
        return Filter(f"{field} lt {format_literal(_to_literal(value))}")

    def le(self, field: str, value: ODataLiteral) -> Filter:
        return Filter(f"{field} le {format_literal(_to_literal(value))}")

    def startswith(self, field: str, value: str) -> Filter:
        return Filter(f"startswith({field},{format_literal(value)})")

    def endswith(self, field: str, value: str) -> Filter:
        return Filter(f"endswith({field},{format_literal(value)})")

    def contains(self, field: str, value: str) -> Filter:
        return Filter(f"contains({field},{format_literal(value)})")

    def and_(self, a: Union[Filter, str], b: Union[Filter, str]) -> Filter:
        return Filter(f"({_coerce(a)}) and ({_coerce(b)})")

    def or_(self, a: Union[Filter, str], b: Union[Filter, str]) -> Filter:
        return Filter(f"({_coerce(a)}) or ({_coerce(b)})")

    def not_(self, a: Union[Filter, str]) -> Filter:
        return Filter(f"not ({_coerce(a)})")

    def raw(self, expr: str) -> Filter:
        """Escape hatch: embed a raw OData filter fragment verbatim."""
        return Filter(expr)


#: Module-level singleton factory, mirroring ``filterFactory`` in TS.
filter_factory = FilterFactory()


def _to_literal(v: ODataLiteral) -> Any:
    """Convert ``None`` to a sentinel that ``format_literal`` maps to ``null``.

    ``fms_odata_spec.format_literal`` does not accept ``None``; the TS
    ``formatLiteral`` maps ``null``/``undefined`` to the literal ``null``.
    """
    if v is None:
        return _Null()
    return v


class _Null:
    """Sentinel rendered as the OData literal ``null`` by :func:`format_literal`."""

    def __repr__(self) -> str:
        return "Null"


# Monkeypatch-free: extend format_literal handling for _Null via a wrapper.
# fms_odata_spec.format_literal falls through to ``str(value)`` for unknown
# types, so we wrap the call to handle None ourselves.
_orig_format_literal = format_literal


def _format_literal_or_null(value: Any) -> str:
    if isinstance(value, _Null):
        return "null"
    return _orig_format_literal(value)


# Rebind the name used by FilterFactory so None renders as "null".
# (We import the spec function under the same name, so we patch our local
# reference rather than the spec module.)
format_literal = _format_literal_or_null  # type: ignore[assignment]


#: Input accepted by :meth:`Query.filter`: a :class:`Filter`, a raw string,
#: or a callable that receives a :class:`FilterFactory`.
FilterInput = Union[Filter, str, Callable[["FilterFactory"], Union[Filter, str]]]

#: Sort direction for ``$orderby``.
OrderDir = str  # "asc" | "desc"


class _QueryState:
    """Internal accumulator for query options."""

    __slots__ = (
        "select",
        "filter",
        "expand",
        "orderby",
        "top",
        "skip",
        "count",
        "search",
        "apply",
    )

    def __init__(self) -> None:
        self.select: Optional[List[str]] = None
        self.filter: Optional[str] = None
        self.expand: Optional[List[Dict[str, Any]]] = None
        self.orderby: Optional[List[Dict[str, str]]] = None
        self.top: Optional[int] = None
        self.skip: Optional[int] = None
        self.count: Optional[bool] = None
        self.search: Optional[str] = None
        self.apply: Optional[str] = None


class QueryResult:
    """Result envelope returned by :meth:`Query.get`."""

    __slots__ = ("value", "count", "next_link")

    def __init__(
        self,
        value: List[Any],
        count: Optional[int] = None,
        next_link: Optional[str] = None,
    ) -> None:
        self.value = value
        self.count = count
        self.next_link = next_link

    def __repr__(self) -> str:
        return f"QueryResult(value={self.value!r}, count={self.count!r}, next_link={self.next_link!r})"


class Query:
    """Fluent query builder. Methods mutate and return ``self`` for chaining.

    Obtain an instance via ``client.from(entity_set)``.
    """

    def __init__(self, base_url: str, entity_set: str, client: Any = None) -> None:
        self._base_url = base_url
        self._entity_set = entity_set
        self._client = client
        self._state = _QueryState()

    # -- builder methods --------------------------------------------------

    def select(self, *fields: str) -> "Query":
        """Add fields to ``$select`` (cumulative)."""
        if self._state.select is None:
            self._state.select = []
        self._state.select.extend(fields)
        return self

    def filter(self, input: FilterInput) -> "Query":
        """Add a ``$filter`` condition. Multiple calls AND together."""
        expr = _resolve_filter(input)
        if self._state.filter:
            self._state.filter = f"({self._state.filter}) and ({expr})"
        else:
            self._state.filter = expr
        return self

    def or_(self, input: FilterInput) -> "Query":
        """OR a condition with the existing ``$filter``."""
        expr = _resolve_filter(input)
        if self._state.filter:
            self._state.filter = f"({self._state.filter}) or ({expr})"
        else:
            self._state.filter = expr
        return self

    def expand(
        self, name: str, build: Optional[Callable[["Query"], None]] = None
    ) -> "Query":
        """Add a ``$expand`` navigation property, optionally with nested options."""
        entry: Dict[str, Any] = {"name": name}
        if build is not None:
            nested = Query("", name)
            build(nested)
            entry["options"] = nested._state
        if self._state.expand is None:
            self._state.expand = []
        self._state.expand.append(entry)
        return self

    def orderby(self, field: str, direction: OrderDir = "asc") -> "Query":
        """Add an ``$orderby`` clause (cumulative)."""
        if self._state.orderby is None:
            self._state.orderby = []
        self._state.orderby.append({"field": field, "dir": direction})
        return self

    def top(self, n: int) -> "Query":
        """Set ``$top``. Must be a non-negative integer."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise ValueError(f"Query.top: expected non-negative integer, got {n}")
        self._state.top = n
        return self

    def skip(self, n: int) -> "Query":
        """Set ``$skip``. Must be a non-negative integer."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise ValueError(f"Query.skip: expected non-negative integer, got {n}")
        self._state.skip = n
        return self

    def count(self, enabled: bool = True) -> "Query":
        """Enable/disable ``$count``."""
        self._state.count = enabled
        return self

    def search(self, term: str) -> "Query":
        """Set ``$search`` (verbatim)."""
        self._state.search = term
        return self

    # -- $apply (aggregation) -- requires FMS 22.0.1+ (FileMaker 2024) -----

    def apply(self, expr: str) -> "Query":
        """Set a raw ``$apply`` expression."""
        self._state.apply = expr
        return self

    def aggregate(
        self, expressions: Sequence[Dict[str, Any]]
    ) -> "Query":
        """Aggregate the entity set. Produces ``$apply=aggregate(...)``.

        Each expression is ``{"field": str, "function": AggregateFunction,
        "alias": str}``.
        """
        parts = [f"{e['field']} with {e['function']} as {e['alias']}" for e in expressions]
        self._state.apply = f"aggregate({','.join(parts)})"
        return self

    def group_by(
        self,
        fields: Sequence[str],
        aggregate_expressions: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> "Query":
        """Group by fields, optionally with aggregation.

        Produces ``$apply=groupby((fields), aggregate(...))``.
        """
        field_list = ",".join(fields)
        if aggregate_expressions:
            agg_parts = [
                f"{e['field']} with {e['function']} as {e['alias']}"
                for e in aggregate_expressions
            ]
            self._state.apply = (
                f"groupby(({field_list}),aggregate({','.join(agg_parts)}))"
            )
        else:
            self._state.apply = f"groupby(({field_list}))"
        return self

    # -- URL building -----------------------------------------------------

    def to_url(self) -> str:
        """Build the absolute request URL for this query."""
        qs = _serialize_options(self._state, top_level=True)
        base = f"{self._base_url}/{encode_path_segment(self._entity_set)}"
        return f"{base}?{qs}" if qs else base

    # -- entity handle ----------------------------------------------------

    def by_key(self, key: Union[str, int]) -> EntityRef:
        """Get a handle to a single entity by its primary key."""
        if self._client is None:
            raise RuntimeError("Query.by_key: no client attached (use FMSODataClient.from)")
        return EntityRef(self._client, self._entity_set, key)

    # -- execution --------------------------------------------------------

    def create(self, body: Dict[str, Any]) -> Any:
        """POST a new entity to the collection. Returns the created row."""
        if self._client is None:
            raise RuntimeError("Query.create: no client attached (use FMSODataClient.from)")
        import json as _json

        url = f"{self._base_url}/{encode_path_segment(self._entity_set)}"
        return execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps(body),
                accept="json",
            ),
        )

    def get(self) -> QueryResult:
        """Execute the query. Returns the parsed OData collection envelope."""
        if self._client is None:
            raise RuntimeError("Query.get: no client attached (use FMSODataClient.from)")
        envelope = execute_json(
            self._client._ctx,
            self.to_url(),
            HttpRequestOptions(method="GET", accept="json"),
        )
        value = (envelope or {}).get("value", []) if isinstance(envelope, dict) else []
        count = None
        next_link = None
        if isinstance(envelope, dict):
            if isinstance(envelope.get("@odata.count"), int):
                count = envelope["@odata.count"]
            if isinstance(envelope.get("@odata.nextLink"), str):
                next_link = envelope["@odata.nextLink"]
        return QueryResult(value=value, count=count, next_link=next_link)

    def script(self, name: str, parameter: Optional[str] = None) -> Any:
        """Invoke a FileMaker script at entity-set scope.

        Filter/select/orderby/paging state on the Query is ignored -- the
        underlying OData Action only cares about the entity set.
        """
        if self._client is None:
            raise RuntimeError("Query.script: no client attached (use FMSODataClient.from)")
        from .scripts import run_script_at_entity_set

        return run_script_at_entity_set(self._client, self._entity_set, name, parameter)


def _resolve_filter(input: FilterInput) -> str:
    if callable(input):
        return _coerce(input(filter_factory))
    return _coerce(input)


def _serialize_options(state: _QueryState, *, top_level: bool) -> str:
    """Serialize query options as a top-level querystring or a nested
    ``$expand`` option block (semicolon-joined, unencoded)."""
    pairs: List[tuple] = []

    if state.select:
        pairs.append(("$select", ",".join(state.select)))
    if state.filter:
        pairs.append(("$filter", state.filter))
    if state.expand:
        parts = []
        for e in state.expand:
            if not e.get("options"):
                parts.append(e["name"])
            else:
                inner = _serialize_options(e["options"], top_level=False)
                parts.append(f"{e['name']}({inner})" if inner else e["name"])
        pairs.append(("$expand", ",".join(parts)))
    if state.orderby:
        pairs.append(
            ("$orderby", ",".join(f"{o['field']} {o['dir']}" for o in state.orderby))
        )
    if state.top is not None:
        pairs.append(("$top", str(state.top)))
    if state.skip is not None:
        pairs.append(("$skip", str(state.skip)))
    if state.count:
        pairs.append(("$count", "true"))
    if state.search:
        pairs.append(("$search", state.search))
    if state.apply:
        pairs.append(("$apply", state.apply))

    if top_level:
        return build_query_string(pairs)
    return ";".join(f"{k}={v}" for k, v in pairs)
