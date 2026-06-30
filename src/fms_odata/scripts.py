"""FileMaker script invocation.

Mirrors ``src/scripts.ts`` in fms-odata-js. FMS exposes FileMaker scripts
through the OData v4 Action mechanism at a ``Script.<ScriptName>`` path
suffix. Scripts can be invoked at three scopes:

    POST /<db>/Script.<name>                        // database-level
    POST /<db>/<EntitySet>/Script.<name>            // entity-set context
    POST /<db>/<EntitySet>(<key>)/Script.<name>     // single-record context

Starting with FileMaker Server 2026 (v26), scripts can also be invoked by
their immutable FMSID instead of the name:

    POST /<db>/Script.FMSID:<id>

The optional parameter is sent as ``{"scriptParameterValue": "<string>"}``.
The response envelope is ``{"scriptResult": "...", "scriptError": "0"}``
(flat, older FMS) or
``{"scriptResult": {"code": 0, "resultParameter": "..."}}`` (nested, v26+);
a non-zero error becomes ``FMScriptError``.

Reuses :func:`fms_odata_spec.parse_script_response` for envelope parsing and
raises ``FMScriptError`` on non-zero codes, matching the TS behaviour.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from fms_odata_spec import FMScriptError, RequestRef, ScriptResult, parse_script_response

from .http import HttpRequestOptions, execute_json
from .url import encode_path_segment, escape_string_literal

__all__ = ["ScriptInvoker", "ScriptResult", "run_script_at_database"]


def _format_key(key: Union[str, int, bool]) -> str:
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, str):
        return f"'{escape_string_literal(key)}'"
    raise TypeError("ScriptInvoker: unsupported key type")


class ScriptInvoker:
    """Low-level handle used internally by the client, query, and entity ref.

    Exposed so advanced callers can build their own invocation paths if needed.
    """

    def __init__(
        self,
        client: Any,
        entity_set: Optional[str] = None,
        key: Optional[Union[str, int, bool]] = None,
    ) -> None:
        self._client = client
        self.entity_set = entity_set
        self.key = key

    def url(self, name: str) -> str:
        """Build the absolute URL for invoking ``name`` at this scope."""
        if not name:
            raise TypeError("ScriptInvoker: script name is required")
        return self._url_for_segment(f"Script.{encode_path_segment(name)}")

    def url_by_id(self, fmsid: int) -> str:
        """Build the absolute URL for invoking by FMSID at this scope."""
        if not isinstance(fmsid, int) or fmsid != fmsid:
            raise TypeError("ScriptInvoker: fmsid must be a finite integer")
        return self._url_for_segment(f"Script.FMSID:{fmsid}")

    def _url_for_segment(self, script_segment: str) -> str:
        base = self._client.base_url
        if self.entity_set is None:
            return f"{base}/{script_segment}"
        set_segment = encode_path_segment(self.entity_set)
        if self.key is None:
            return f"{base}/{set_segment}/{script_segment}"
        return f"{base}/{set_segment}({_format_key(self.key)})/{script_segment}"

    def run(self, name: str, parameter: Optional[str] = None) -> ScriptResult:
        """Invoke the script by name. Returns a :class:`ScriptResult` on success."""
        return self._run_at_url(self.url(name), parameter)

    def run_by_id(self, fmsid: int, parameter: Optional[str] = None) -> ScriptResult:
        """Invoke the script by its immutable FMSID (v26+)."""
        return self._run_at_url(self.url_by_id(fmsid), parameter)

    def _run_at_url(self, url: str, parameter: Optional[str]) -> ScriptResult:
        import json as _json

        headers: dict = {}
        content: Optional[str] = None
        if parameter is not None:
            headers["Content-Type"] = "application/json"
            content = _json.dumps({"scriptParameterValue": parameter})

        raw = execute_json(
            self._client._ctx,
            url,
            HttpRequestOptions(
                method="POST",
                headers=headers or None,
                content=content,
                accept="json",
            ),
        )
        return _parse_and_raise(raw, url)


def _parse_and_raise(raw: Any, url: str) -> ScriptResult:
    """Parse the script envelope and raise ``FMScriptError`` on non-zero codes.

    Handles both the flat (older FMS) and nested (v26+) envelope shapes, then
    delegates to :func:`fms_odata_spec.parse_script_response` for the common
    path while preserving the TS behaviour of raising on non-zero errors.
    """
    envelope = raw if isinstance(raw, dict) else {}
    raw_result = envelope.get("scriptResult")

    if (
        raw_result is not None
        and isinstance(raw_result, dict)
        and "resultParameter" in raw_result
    ):
        # Nested envelope (FMS v26+): code + resultParameter inside scriptResult.
        code = raw_result.get("code")
        try:
            script_error = str(int(code)) if code is not None else "0"
        except (ValueError, TypeError):
            script_error = "0"
        result_param = (
            str(raw_result.get("resultParameter"))
            if raw_result.get("resultParameter") is not None
            else None
        )
    else:
        # Flat envelope (older FMS): scriptResult is a string, scriptError sibling.
        script_error = str(envelope.get("scriptError", "0"))
        if raw_result is not None:
            result_param = raw_result if isinstance(raw_result, str) else _json_dumps(raw_result)
        else:
            result_param = None

    if script_error != "0":
        raise FMScriptError(
            f"FileMaker script error {script_error}",
            script_error=int(script_error),
            script_result=result_param,
            request=RequestRef(method="POST", url=url),
        )

    # Build a ScriptResult via the spec parser for forward-compat, then patch
    # fields to match the TS shape callers expect.
    parsed = parse_script_response(raw)
    return ScriptResult(
        code=parsed.code,
        raw=parsed.raw,
        result_parameter=result_param,
    )


def _json_dumps(v: Any) -> str:
    import json as _json

    return _json.dumps(v)


def run_script_at_database(
    client: Any, name: str, parameter: Optional[str] = None
) -> ScriptResult:
    """Invoke a script at database scope."""
    return ScriptInvoker(client).run(name, parameter)


def run_script_by_id_at_database(
    client: Any, fmsid: int, parameter: Optional[str] = None
) -> ScriptResult:
    """Invoke a script by FMSID at database scope (v26+)."""
    return ScriptInvoker(client).run_by_id(fmsid, parameter)


def run_script_at_entity_set(
    client: Any, entity_set: str, name: str, parameter: Optional[str] = None
) -> ScriptResult:
    """Invoke a script at entity-set scope."""
    return ScriptInvoker(client, entity_set=entity_set).run(name, parameter)


def run_script_at_entity(
    client: Any,
    entity_set: str,
    key: Union[str, int, bool],
    name: str,
    parameter: Optional[str] = None,
) -> ScriptResult:
    """Invoke a script at single-record scope."""
    return ScriptInvoker(client, entity_set=entity_set, key=key).run(name, parameter)
