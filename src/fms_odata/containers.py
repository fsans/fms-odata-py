"""FileMaker container field I/O.

Mirrors ``src/containers.ts`` in fms-odata-js, adapted to Python idioms:

- Downloads return ``bytes`` (not ``Blob``).
- Streaming uses ``httpx.Response.iter_bytes()`` (an iterator yielding
  ``bytes`` chunks), consistent with how httpx itself exposes streaming.

FMS exposes three container operations over OData v4:

    GET   /<EntitySet>(<key>)/<field>/$value   -> ContainerRef.get / get_stream
    PATCH /<EntitySet>(<key>)/<field>          -> ContainerRef.upload (binary)
    PATCH /<EntitySet>(<key>)  (JSON body)     -> ContainerRef.upload (base64)

Supported MIME types: PNG, JPEG, GIF, TIFF, PDF.
"""

from __future__ import annotations

import base64
import re
from typing import Iterator, Optional

from fms_odata_spec import sniff_container_mime

from .http import HttpRequestOptions, execute_request
from .url import encode_path_segment

__all__ = [
    "ContainerDownload",
    "ContainerRef",
    "FM_CONTAINER_SUPPORTED_MIME_TYPES",
]

#: MIME types FMS accepts for container fields.
FM_CONTAINER_SUPPORTED_MIME_TYPES = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/tiff",
    "application/pdf",
)


class ContainerDownload:
    """Result of a successful container download."""

    __slots__ = ("content", "content_type", "filename", "size")

    def __init__(
        self,
        content: bytes,
        content_type: str,
        size: int,
        filename: Optional[str] = None,
    ) -> None:
        self.content = content
        self.content_type = content_type
        self.size = size
        self.filename = filename

    def __repr__(self) -> str:
        return f"ContainerDownload(size={self.size}, content_type={self.content_type!r}, filename={self.filename!r})"


def _parse_content_disposition_filename(disposition: str) -> Optional[str]:
    """Parse a Content-Disposition header for the filename."""
    # Prefer RFC 5987 filename*.
    star_match = re.search(r"""filename\*\s*=\s*[^']*''([^"]+)""", disposition)
    if star_match:
        from urllib.parse import unquote

        return unquote(star_match.group(1))
    quoted = re.search(r'filename="([^"]+)"', disposition)
    if quoted:
        return quoted.group(1)
    unquoted = re.search(r"filename=([^\s;]+)", disposition)
    if unquoted:
        return unquoted.group(1)
    return None


def _to_bytes(data) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    raise TypeError("ContainerRef.upload: data must be bytes-like")


def _normalize_mime(value: str) -> str:
    return (value.split(";")[0] or "").strip().lower()


def _is_supported_mime(value: str) -> bool:
    return _normalize_mime(value) in FM_CONTAINER_SUPPORTED_MIME_TYPES


class ContainerRef:
    """Handle to a single FileMaker container field on a specific record.

    Created via ``entity_ref.container(field_name)``.
    """

    def __init__(self, entity, field_name: str) -> None:
        if not field_name:
            raise TypeError("ContainerRef: field_name is required")
        self._entity = entity
        self.field_name = field_name

    def url(self) -> str:
        """Absolute URL of the container field (used by binary upload)."""
        return f"{self._entity.to_url()}/{encode_path_segment(self.field_name)}"

    def _value_url(self) -> str:
        return f"{self.url()}/$value"

    def get(self) -> ContainerDownload:
        """Download the container's contents into memory as ``bytes``."""
        # FMS quirk: Accept: application/octet-stream makes $value return the
        # stored filename string as text/plain instead of the binary. Use */*.
        res = execute_request(
            self._entity._client._ctx,
            self._value_url(),
            HttpRequestOptions(method="GET", accept="none"),
        )
        content_type = res.headers.get("content-type", "")
        disposition = res.headers.get("content-disposition")
        filename = _parse_content_disposition_filename(disposition) if disposition else None
        content = res.content
        return ContainerDownload(
            content=content,
            content_type=content_type,
            size=len(content),
            filename=filename,
        )

    def get_stream(self, chunk_size: int = 1024) -> Iterator[bytes]:
        """Stream the container's contents without buffering.

        Yields ``bytes`` chunks. Useful for large files.
        """
        res = execute_request(
            self._entity._client._ctx,
            self._value_url(),
            HttpRequestOptions(method="GET", accept="none"),
        )
        return res.iter_bytes(chunk_size=chunk_size)

    def upload(
        self,
        data,
        content_type: Optional[str] = None,
        filename: Optional[str] = None,
        encoding: str = "binary",
    ) -> None:
        """Upload contents to the container. Replaces any existing value.

        Args:
            data: Bytes-like payload.
            content_type: MIME type. When omitted, sniffed from magic bytes.
            filename: Optional filename stored in the container.
            encoding: ``"binary"`` (default, PATCH ``.../<field>`` with raw
                bytes, restricted to PNG/JPEG/GIF/TIFF/PDF) or ``"base64"``
                (PATCH ``.../<EntitySet>(<key>)`` with JSON body + annotations).
        """
        raw = _to_bytes(data)
        if content_type is None:
            sniffed = sniff_container_mime(raw)
            if sniffed is None:
                raise TypeError(
                    "ContainerRef.upload: cannot sniff content_type from payload; "
                    "pass content_type explicitly."
                )
            content_type = sniffed

        if encoding == "binary":
            if not _is_supported_mime(content_type):
                raise TypeError(
                    f"ContainerRef.upload: binary upload restricted to "
                    f"{FM_CONTAINER_SUPPORTED_MIME_TYPES}; got {content_type!r}"
                )
            headers = {"Content-Type": content_type}
            if filename:
                headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            execute_request(
                self._entity._client._ctx,
                self.url(),
                HttpRequestOptions(
                    method="PATCH",
                    headers=headers,
                    content=raw,
                    accept="none",
                ),
            )
        elif encoding == "base64":
            import json as _json

            body: dict = {}
            body[self.field_name] = base64.b64encode(raw).decode("ascii")
            body[f"{self.field_name}@com.filemaker.odata.ContentType"] = content_type
            if filename:
                body[f"{self.field_name}@com.filemaker.odata.Filename"] = filename
            execute_request(
                self._entity._client._ctx,
                self._entity.to_url(),
                HttpRequestOptions(
                    method="PATCH",
                    headers={"Content-Type": "application/json"},
                    content=_json.dumps(body),
                    accept="none",
                ),
            )
        else:
            raise ValueError(f"ContainerRef.upload: unknown encoding {encoding!r}")

    def delete(self) -> None:
        """Clear the container by PATCHing the record with ``{field: null}``."""
        import json as _json

        execute_request(
            self._entity._client._ctx,
            self._entity.to_url(),
            HttpRequestOptions(
                method="PATCH",
                headers={"Content-Type": "application/json"},
                content=_json.dumps({self.field_name: None}),
                accept="none",
            ),
        )
