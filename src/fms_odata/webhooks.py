"""Webhook management for FileMaker Server OData.

Mirrors ``src/webhooks.ts`` in fms-odata-js. FMS exposes webhook management
through five POST endpoints:

    POST /<db>/Webhook.Add      -- create a webhook
    POST /<db>/Webhook.Remove   -- delete a webhook
    POST /<db>/Webhook.Get      -- get a specific webhook's data
    POST /<db>/Webhook.GetAll   -- list all webhooks
    POST /<db>/Webhook.Invoke   -- manually trigger a webhook (for testing)

Webhooks require FileMaker Server 2023+ (v21).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .http import HttpRequestOptions, execute_json

__all__ = ["WebhookManager"]


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


class WebhookManager:
    """Webhook manager for FileMaker Server webhook CRUD.

    Obtain an instance via ``client.webhooks()`` or use the convenience methods
    on :class:`fms_odata.client.FMSODataClient`. Requires FMS 2023+ (v21).
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def _url(self, operation: str) -> str:
        return f"{self._client.base_url}/Webhook.{operation}"

    def create(self, params: Dict[str, Any]) -> Any:
        """Create a webhook."""
        if not params.get("webhook"):
            raise TypeError("WebhookManager: `webhook` URL is required")
        if not params.get("tableName"):
            raise TypeError("WebhookManager: `tableName` is required")
        import json as _json

        return execute_json(
            self._client._ctx,
            self._url("Add"),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps(_normalize_create_params(params)),
                accept="json",
            ),
        )

    def remove(self, webhook_id: str) -> Any:
        """Remove (delete) a webhook by its ID."""
        if not webhook_id:
            raise TypeError("WebhookManager: webhook `id` is required")
        import json as _json

        return execute_json(
            self._client._ctx,
            self._url("Remove"),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"id": webhook_id}),
                accept="json",
            ),
        )

    def get(self, webhook_id: str) -> Any:
        """Get a specific webhook's data by ID."""
        if not webhook_id:
            raise TypeError("WebhookManager: webhook `id` is required")
        import json as _json

        return execute_json(
            self._client._ctx,
            self._url("Get"),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"id": webhook_id}),
                accept="json",
            ),
        )

    def get_all(self) -> Any:
        """List all webhooks."""
        return execute_json(
            self._client._ctx,
            self._url("GetAll"),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                accept="json",
            ),
        )

    def invoke(self, webhook_id: str) -> Any:
        """Manually invoke (trigger) a webhook by ID. Useful for testing."""
        if not webhook_id:
            raise TypeError("WebhookManager: webhook `id` is required")
        import json as _json

        return execute_json(
            self._client._ctx,
            self._url("Invoke"),
            HttpRequestOptions(
                method="POST",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({"id": webhook_id}),
                accept="json",
            ),
        )
