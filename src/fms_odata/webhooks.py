"""Webhook management for FileMaker Server OData.

Mirrors ``src/webhooks.ts`` in fms-odata-js. FMS exposes webhook management
through five endpoints following the standard OData function-call shape: read
endpoints use GET, and action endpoints use POST with the ``<id>`` passed as a
function argument in the URL path.

    GET  /<db>/Webhook.GetAll        -- list all webhooks
    GET  /<db>/Webhook.Get(<id>)     -- get one webhook by id
    POST /<db>/Webhook.Add           -- create a webhook (config in JSON body)
    POST /<db>/Webhook.Delete(<id>)  -- delete a webhook (id in URL path)
    POST /<db>/Webhook.Invoke(<id>)  -- manually trigger a webhook (id in URL path)

Webhooks require FileMaker Server 2025+ (v22). Use
``db.has_feature('webhooks')`` to check before calling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from .http import HttpRequestOptions, execute_json
from .url import encode_path_segment

__all__ = ["WebhookManager"]

WebhookId = Union[str, int]


def _normalize_create_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Merge legacy ``headers`` into ``endpointHeaders``."""
    out: Dict[str, Any] = {
        "webhook": params.get("webhook"),
        "tableName": params.get("tableName"),
    }
    if params.get("endpointHeaders"):
        out["endpointHeaders"] = params["endpointHeaders"]
    if params.get("headers") and not params.get("endpointHeaders"):
        out["endpointHeaders"] = params["headers"]
    if params.get("queryHeaders"):
        out["queryHeaders"] = params["queryHeaders"]
    if params.get("notifySchemaChanges") is not None:
        out["notifySchemaChanges"] = params["notifySchemaChanges"]
    if params.get("select"):
        out["select"] = params["select"]
    if params.get("filter"):
        out["filter"] = params["filter"]
    if params.get("maxFailedAttempts") is not None:
        out["maxFailedAttempts"] = params["maxFailedAttempts"]
    return out


def _extract_webhook_id(data: Any) -> Optional[str]:
    """Extract the webhook ID from a ``Webhook.Add`` response.

    FMS returns ``{ webhookResult: { webhookID: N } }``. Older or alternate
    shapes (``{ webhookID: N }``, ``{ id: N }``) are accepted as fallbacks.
    """
    if not isinstance(data, dict):
        return None
    from_result = data.get("webhookResult")
    if isinstance(from_result, dict):
        wid = from_result.get("webhookID")
        if wid is not None:
            return str(wid)
    wid = data.get("webhookID")
    if wid is not None:
        return str(wid)
    wid = data.get("id")
    if wid is not None:
        return str(wid)
    return None


class WebhookManager:
    """Webhook manager for FileMaker Server webhook CRUD.

    Obtain an instance via ``client.webhooks()`` or use the convenience methods
    on :class:`fms_odata.client.FMSODataClient`.

    Requires FileMaker Server 2025+ (v22).
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def _url(
        self, operation: str, id: Optional[WebhookId] = None
    ) -> str:
        base = f"{self._client.base_url}/Webhook.{operation}"
        if id is not None:
            return f"{base}({encode_path_segment(str(id))})"
        return base

    def create(self, params: Dict[str, Any]) -> Dict[str, str]:
        """Create a webhook.

        Returns a dict with the server-generated ``id`` of the new webhook::

            {"id": "42"}
        """
        if not params.get("webhook"):
            raise TypeError("WebhookManager: `webhook` URL is required")
        if not params.get("tableName"):
            raise TypeError("WebhookManager: `tableName` is required")
        import json as _json

        data = execute_json(
            self._client._ctx,
            self._url("Add"),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps(_normalize_create_params(params)),
                accept="json",
            ),
        )
        wid = _extract_webhook_id(data)
        if wid is None:
            raise RuntimeError("WebhookManager: Webhook.Add did not return a webhook id")
        return {"id": wid}

    def remove(self, webhook_id: WebhookId) -> Any:
        """Delete a webhook by its ID."""
        if webhook_id == "" or webhook_id is None:
            raise TypeError("WebhookManager: webhook `id` is required")
        return execute_json(
            self._client._ctx,
            self._url("Delete", webhook_id),
            HttpRequestOptions(
                method="POST",
                accept="json",
            ),
        )

    def delete(self, webhook_id: WebhookId) -> Any:
        """Alias for :meth:`remove` (matches the FMS endpoint name ``Webhook.Delete``)."""
        return self.remove(webhook_id)

    def get(self, webhook_id: WebhookId) -> Any:
        """Get a specific webhook's data by ID."""
        if webhook_id == "" or webhook_id is None:
            raise TypeError("WebhookManager: webhook `id` is required")
        return execute_json(
            self._client._ctx,
            self._url("Get", webhook_id),
            HttpRequestOptions(
                method="GET",
                accept="json",
            ),
        )

    def get_all(self) -> Any:
        """List all webhooks."""
        return execute_json(
            self._client._ctx,
            self._url("GetAll"),
            HttpRequestOptions(
                method="GET",
                accept="json",
            ),
        )

    def invoke(
        self, webhook_id: WebhookId, *, row_ids: Optional[List[Union[str, int]]] = None
    ) -> Any:
        """Manually invoke (trigger) a webhook by ID. Useful for testing.

        Optionally pass ``row_ids`` to target specific records; if omitted, FMS
        triggers the webhook for all pending records.
        """
        if webhook_id == "" or webhook_id is None:
            raise TypeError("WebhookManager: webhook `id` is required")
        import json as _json

        # FMS requires a JSON body for Invoke (it rejects empty bodies with a
        # JSON syntax error). Send { rowIDs: [...] } -- an empty array triggers
        # the webhook for all pending records.
        body = _json.dumps({"rowIDs": list(row_ids) if row_ids else []})
        return execute_json(
            self._client._ctx,
            self._url("Invoke", webhook_id),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=body,
                accept="json",
            ),
        )
