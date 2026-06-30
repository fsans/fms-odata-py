"""Tests for container field I/O.

Ports ``tests/unit/containers.test.ts`` from fms-odata-js, adapted to bytes
(instead of Blob) and httpx streaming.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from fms_odata import FM_CONTAINER_SUPPORTED_MIME_TYPES
from fms_odata.containers import _parse_content_disposition_filename
from fms_odata_spec import sniff_container_mime

from .conftest import BASE, make_client, text_response

PNG_BYTES = bytes.fromhex("89504e470d0a1a0a0000000d49484452")
JPEG_BYTES = bytes.fromhex("ffd8ffe000104a464946")
GIF_BYTES = b"GIF89a"
TIFF_LE = bytes.fromhex("49492a00")
TIFF_BE = bytes.fromhex("4d4d002a")
PDF_BYTES = b"%PDF-1.4"


# -- parseContentDispositionFilename ---------------------------------------


def test_parse_disposition_quoted_filename():
    assert _parse_content_disposition_filename('attachment; filename="logo.png"') == "logo.png"


def test_parse_disposition_unquoted_filename():
    assert _parse_content_disposition_filename("attachment; filename=logo.png") == "logo.png"


def test_parse_disposition_rfc5987_filename_star_preferred():
    assert (
        _parse_content_disposition_filename(
            'attachment; filename="ascii.png"; filename*=UTF-8\'\'na%C3%AFve%20file.png'
        )
        == "naïve file.png"
    )


# -- sniffContainerMime (reused from spec) ---------------------------------


def test_sniff_png():
    assert sniff_container_mime(PNG_BYTES) == "image/png"


def test_sniff_jpeg():
    assert sniff_container_mime(JPEG_BYTES) == "image/jpeg"


def test_sniff_gif():
    assert sniff_container_mime(GIF_BYTES) == "image/gif"


def test_sniff_tiff_little_endian():
    assert sniff_container_mime(TIFF_LE) == "image/tiff"


def test_sniff_tiff_big_endian():
    assert sniff_container_mime(TIFF_BE) == "image/tiff"


def test_sniff_pdf():
    assert sniff_container_mime(PDF_BYTES) == "application/pdf"


def test_sniff_unknown_returns_none():
    assert sniff_container_mime(b"\x00\x01\x02") is None


# -- ContainerRef.get -------------------------------------------------------


def test_container_get_returns_bytes():
    def handler(req):
        assert str(req.url) == f"{BASE}/contact(7)/photo/$value"
        return text_response(
            PNG_BYTES,
            headers={
                "content-type": "image/png",
                "content-disposition": 'attachment; filename="p.png"',
            },
        )

    db = make_client(handler)
    dl = db.from_("contact").by_key(7).container("photo").get()
    assert dl.content == PNG_BYTES
    assert dl.content_type == "image/png"
    assert dl.size == len(PNG_BYTES)
    assert dl.filename == "p.png"
    db.close()


def test_container_get_stream_yields_chunks():
    def handler(req):
        return text_response(PNG_BYTES, headers={"content-type": "image/png"})

    db = make_client(handler)
    chunks = list(db.from_("contact").by_key(7).container("photo").get_stream())
    assert b"".join(chunks) == PNG_BYTES
    db.close()


# -- ContainerRef.upload ----------------------------------------------------


def test_container_upload_binary_sniffs_mime():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["content_type"] = req.headers.get("content-type")
        captured["body"] = req.content
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.from_("contact").by_key(7).container("photo").upload(PNG_BYTES, filename="p.png")
    assert captured["url"] == f"{BASE}/contact(7)/photo"
    assert captured["method"] == "PATCH"
    assert captured["content_type"] == "image/png"
    assert captured["body"] == PNG_BYTES
    db.close()


def test_container_upload_binary_rejects_unsupported_mime():
    db = make_client(lambda req: httpx.Response(204, request=req))
    with pytest.raises(TypeError, match="restricted"):
        db.from_("contact").by_key(7).container("photo").upload(
            b"\x00\x01", content_type="application/zip"
        )
    db.close()


def test_container_upload_base64_sends_json_annotations():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["content_type"] = req.headers.get("content-type")
        import json as _json

        captured["body"] = _json.loads(req.content)
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.from_("contact").by_key(7).container("photo").upload(
        PNG_BYTES, content_type="image/png", filename="p.png", encoding="base64"
    )
    assert captured["url"] == f"{BASE}/contact(7)"
    assert captured["content_type"] == "application/json"
    assert captured["body"]["photo"] == base64.b64encode(PNG_BYTES).decode("ascii")
    assert captured["body"]["photo@com.filemaker.odata.ContentType"] == "image/png"
    assert captured["body"]["photo@com.filemaker.odata.Filename"] == "p.png"
    db.close()


def test_container_delete_clears_field():
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["method"] = req.method
        import json as _json

        captured["body"] = _json.loads(req.content)
        return httpx.Response(204, request=req)

    db = make_client(handler)
    db.from_("contact").by_key(7).container("photo").delete()
    assert captured["url"] == f"{BASE}/contact(7)"
    assert captured["method"] == "PATCH"
    assert captured["body"] == {"photo": None}
    db.close()
