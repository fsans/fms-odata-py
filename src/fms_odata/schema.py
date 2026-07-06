"""Schema modification (DDL) for FileMaker Server via the OData system tables.

Mirrors ``src/schema.ts`` in fms-odata-js. FMS exposes DDL through two system
tables:

    FileMaker_Tables   -- create tables, add fields, delete tables/fields
    FileMaker_Indexes  -- create and delete field indexes

All operations require a FileMaker account with full access privileges.
Destructive operations (``delete_table``, ``delete_field``) require an
explicit ``confirm=True`` to prevent accidental data loss.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fms_odata_spec import FIELD_TYPES, parse_field_type

from .http import HttpRequestOptions, execute_json
from .url import encode_path_segment

__all__ = ["SchemaEditor"]


def _validate_field_definitions(fields: List[Dict[str, Any]]) -> None:
    for f in fields:
        if not f.get("name"):
            raise TypeError("SchemaEditor: field `name` is required")
        if not f.get("type"):
            raise TypeError("SchemaEditor: field `type` is required")
        parsed = parse_field_type(f["type"])
        base = parsed.base_type.upper()
        if base not in FIELD_TYPES:
            raise TypeError(
                f'SchemaEditor: unsupported field type "{f["type"]}" (base: "{base}"). '
                f"Supported: {', '.join(FIELD_TYPES)}"
            )


class SchemaEditor:
    """Schema editor for FileMaker DDL operations.

    Obtain an instance via ``client.schema()`` or use the convenience methods
    on :class:`fms_odata.client.FMSODataClient`.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def create_table(self, params: Dict[str, Any]) -> Any:
        """Create a new table with the given field definitions."""
        if not params.get("tableName"):
            raise TypeError("SchemaEditor: `tableName` is required")
        if not params.get("fields"):
            raise TypeError("SchemaEditor: `fields` must be a non-empty list")
        _validate_field_definitions(params["fields"])
        import json as _json

        url = f"{self._client.base_url}/FileMaker_Tables"
        return execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps(params),
                accept="json",
            ),
        )

    def add_fields(self, params: Dict[str, Any]) -> Any:
        """Add fields to an existing table."""
        if not params.get("tableName"):
            raise TypeError("SchemaEditor: `tableName` is required")
        if not params.get("fields"):
            raise TypeError("SchemaEditor: `fields` must be a non-empty list")
        _validate_field_definitions(params["fields"])
        import json as _json

        url = f"{self._client.base_url}/FileMaker_Tables/{encode_path_segment(params['tableName'])}"
        return execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="PATCH",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"fields": params["fields"]}),
                accept="json",
            ),
        )

    def delete_table(self, table_name: str, *, confirm: bool = False) -> None:
        """Delete a table and ALL its records. Irreversible.

        Requires ``confirm=True`` as a safety guard.
        """
        if not table_name:
            raise TypeError("SchemaEditor: `tableName` is required")
        if confirm is not True:
            raise TypeError(
                f'SchemaEditor: delete_table("{table_name}") requires confirm=True -- '
                "this operation permanently destroys the table and all its records."
            )
        url = f"{self._client.base_url}/FileMaker_Tables/{encode_path_segment(table_name)}"
        execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(method="DELETE", accept="json"),
        )

    def delete_field(self, table_name: str, field_name: str, *, confirm: bool = False) -> None:
        """Delete a field from a table. Irreversible.

        Requires ``confirm=True`` as a safety guard.
        """
        if not table_name:
            raise TypeError("SchemaEditor: `tableName` is required")
        if not field_name:
            raise TypeError("SchemaEditor: `fieldName` is required")
        if confirm is not True:
            raise TypeError(
                f'SchemaEditor: delete_field("{table_name}", "{field_name}") requires confirm=True -- '
                "this operation permanently destroys the field and all its data."
            )
        url = (
            f"{self._client.base_url}/FileMaker_Tables/{encode_path_segment(table_name)}"
            f"/{encode_path_segment(field_name)}"
        )
        execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(method="DELETE", accept="json"),
        )

    def create_index(self, table_name: str, field_name: str) -> Any:
        """Create an index on a field."""
        if not table_name:
            raise TypeError("SchemaEditor: `tableName` is required")
        if not field_name:
            raise TypeError("SchemaEditor: `fieldName` is required")
        import json as _json

        url = f"{self._client.base_url}/FileMaker_Indexes/{encode_path_segment(table_name)}"
        return execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"indexName": field_name}),
                accept="json",
            ),
        )

    def delete_index(self, table_name: str, field_name: str) -> None:
        """Delete an index from a field."""
        if not table_name:
            raise TypeError("SchemaEditor: `tableName` is required")
        if not field_name:
            raise TypeError("SchemaEditor: `fieldName` is required")
        url = (
            f"{self._client.base_url}/FileMaker_Indexes/{encode_path_segment(table_name)}"
            f"/{encode_path_segment(field_name)}"
        )
        execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(method="DELETE", accept="json"),
        )
