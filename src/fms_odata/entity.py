"""Single-entity handle returned by :meth:`Query.by_key`.

Mirrors ``src/entity.ts`` in fms-odata-js. Supports ``.get()``, ``.patch()``,
``.delete()``, ``.script()`` (record-scope), and ``.container()`` (container
field binary I/O).

This module is pure URL building + transport delegation -- no I/O leakage
beyond the transport calls themselves, so the planned async client can reuse
it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .http import HttpRequestOptions, execute_json, execute_request
from .url import ODataLiteral, encode_path_segment, escape_string_literal

__all__ = ["EntityRef", "EntityWriteOptions"]


class EntityWriteOptions:
    """Options accepted by mutating entity operations.

    Attributes:
        if_match: Optional ``If-Match`` precondition (ETag) for optimistic
            concurrency.
        return_representation: Whether the server should return the updated
            representation. Defaults to ``False`` (``Prefer: return=minimal``)
            to match FMS behaviour; set to ``True`` to request
            ``Prefer: return=representation``.
    """

    __slots__ = ("if_match", "return_representation")

    def __init__(
        self,
        *,
        if_match: Optional[str] = None,
        return_representation: bool = False,
    ) -> None:
        self.if_match = if_match
        self.return_representation = return_representation


def _format_key(key: Union[str, int, bool]) -> str:
    """Format an OData primary-key literal for a URL path (``EntitySet(key)``)."""
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        if key != key:  # NaN check (NaN != NaN)
            raise TypeError("EntityRef: key must be a finite number")
        return str(key)
    if isinstance(key, str):
        return f"'{escape_string_literal(key)}'"
    raise TypeError("EntityRef: unsupported key type")


class EntityRef:
    """Handle to a single OData entity.

    Holds the client, entity-set name, and primary key; every method builds a
    URL of the form ``<baseUrl>/<EntitySet>(<key>)`` and delegates to the
    shared HTTP executor.
    """

    def __init__(self, client: Any, entity_set: str, key: Union[str, int, bool]) -> None:
        self._client = client
        self.entity_set = entity_set
        self.key = key

    def to_url(self) -> str:
        """Absolute URL for this entity."""
        return f"{self._client.base_url}/{encode_path_segment(self.entity_set)}({_format_key(self.key)})"

    def get(self) -> Any:
        """GET the entity. Returns the parsed JSON row."""
        return execute_json(
            self._client._ctx,
            self.to_url(),
            HttpRequestOptions(method="GET", accept="json"),
        )

    def field_value(self, field_name: str) -> Any:
        """GET a single field's scalar value via the OData property URL.

        FMS responds with ``{ value: ... }``; this unwraps it.
        """
        url = f"{self.to_url()}/{encode_path_segment(field_name)}"
        envelope = execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(method="GET", accept="json"),
        )
        if isinstance(envelope, dict):
            return envelope.get("value")
        return None

    def patch(
        self,
        body: Dict[str, Any],
        opts: Optional[EntityWriteOptions] = None,
    ) -> Any:
        """PATCH the entity with partial values.

        Returns the updated row when the server echoes one
        (``Prefer: return=representation``), otherwise ``None`` on 204.
        """
        import json as _json

        opts = opts or EntityWriteOptions()
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Prefer": "return=representation" if opts.return_representation else "return=minimal",
        }
        if opts.if_match:
            headers["If-Match"] = opts.if_match
        return execute_json(
            self._client._ctx,
            self.to_url(),
            HttpRequestOptions(
                method="PATCH",
                headers=headers,
                content=_json.dumps(body),
                accept="json",
            ),
        )

    def delete(self, opts: Optional[EntityWriteOptions] = None) -> None:
        """DELETE the entity. Resolves (returns None) on success."""
        opts = opts or EntityWriteOptions()
        headers: Dict[str, str] = {}
        if opts.if_match:
            headers["If-Match"] = opts.if_match
        execute_request(
            self._client._ctx,
            self.to_url(),
            HttpRequestOptions(method="DELETE", headers=headers, accept="none"),
        )

    def script(self, name: str, parameter: Optional[str] = None) -> Any:
        """Invoke a FileMaker script in the context of this single record."""
        from .scripts import run_script_at_entity

        return run_script_at_entity(self._client, self.entity_set, self.key, name, parameter)

    def container(self, field_name: str):
        """Get a typed handle to one of this record's container fields."""
        from .containers import ContainerRef

        return ContainerRef(self, field_name)

    # -- Record references ($ref) -- OData standard, supported since FMS 19 --

    def get_refs(self, nav_property: str) -> list:
        """GET ``.../<navProperty>/$ref``. Returns a list of entity references."""
        url = f"{self.to_url()}/{encode_path_segment(nav_property)}/$ref"
        envelope = execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(method="GET", accept="json"),
        )
        if isinstance(envelope, dict):
            if isinstance(envelope.get("value"), list):
                return envelope["value"]
            if "@odata.id" in envelope:
                return [envelope]
        return []

    def add_ref(self, nav_property: str, target_url: str) -> None:
        """POST a new reference to a navigation property."""
        import json as _json

        url = f"{self.to_url()}/{encode_path_segment(nav_property)}/$ref"
        execute_request(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"@odata.id": target_url}),
                accept="none",
            ),
        )

    def set_ref(self, nav_property: str, target_url: str) -> None:
        """PUT (replace) the reference on a single-valued navigation property."""
        import json as _json

        url = f"{self.to_url()}/{encode_path_segment(nav_property)}/$ref"
        execute_request(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="PUT",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"@odata.id": target_url}),
                accept="none",
            ),
        )

    def remove_ref(self, nav_property: str, target_url: str) -> None:
        """DELETE a reference from a navigation property."""
        from urllib.parse import quote

        url = (
            f"{self.to_url()}/{encode_path_segment(nav_property)}/$ref"
            f"?$id={quote(target_url, safe='')}"
        )
        execute_request(
            self._client._ctx,
            url,
            HttpRequestOptions(method="DELETE", accept="none"),
        )
