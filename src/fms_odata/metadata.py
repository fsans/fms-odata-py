"""$metadata (EDMX/CSDL) fetch and lightweight parser.

Mirrors ``src/metadata.ts`` in fms-odata-js. FMS returns a subset of the full
OData CSDL spec; this module parses just what FMS emits: EntityTypes,
EntitySets, and Actions (FileMaker scripts). Uses a dependency-free regex
approach.

Version extraction reuses :func:`fms_odata_spec.parse_server_version`.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from fms_odata_spec import (
    EdmAction,
    EdmEntitySet,
    EdmEntityType,
    EdmProperty,
    FMServerVersion,
    ODataMetadata,
    parse_server_version,
)

from .http import HttpRequestOptions, execute_request

__all__ = ["MetadataFetcher", "ODataMetadata", "MetadataOptions"]


class MetadataOptions:
    """Options for a metadata fetch.

    Attributes:
        refresh: Force refetch, bypassing the internal cache.
    """

    __slots__ = ("refresh",)

    def __init__(self, *, refresh: bool = False) -> None:
        self.refresh = refresh


def _get_attr(text: str, name: str) -> Optional[str]:
    m = re.search(rf'{name}="([^"]*)"', text, re.I)
    return m.group(1) if m else None


def _get_attrs(text: str) -> dict:
    out: dict = {}
    for m in re.finditer(r'(\w+)="([^"]*)"', text):
        out[m.group(1)] = m.group(2)
    return out


def _find_elements(xml: str, tag_name: str) -> List[str]:
    results: List[str] = []
    for m in re.finditer(rf"<(?:[\w]+:)?{tag_name}\b[^>]*>", xml, re.I):
        open_tag = m.group(0)
        if open_tag.rstrip().endswith("/>"):
            results.append(open_tag)
            continue
        start = m.start()
        close_re = re.compile(rf"</(?:[\w]+:)?{tag_name}>", re.I)
        close_m = close_re.search(xml, m.end())
        if close_m:
            results.append(xml[start : close_m.end()])
    return results


def _element_content(xml: str, tag_name: str) -> Optional[str]:
    open_re = re.compile(rf"<(?:[\w]+:)?{tag_name}\b[^>]*>", re.I)
    open_m = open_re.search(xml)
    if not open_m:
        return None
    start = open_m.end()
    close_re = re.compile(rf"</(?:[\w]+:)?{tag_name}>", re.I)
    close_m = close_re.search(xml, start)
    if not close_m:
        return None
    return xml[start : close_m.start()]


def _parse_property(xml: str) -> EdmProperty:
    attrs = _get_attrs(xml)
    nullable = attrs.get("Nullable", "true") == "true"
    max_length_raw = attrs.get("MaxLength")
    max_length = int(max_length_raw) if max_length_raw and max_length_raw.isdigit() else None
    return EdmProperty(
        name=attrs.get("Name", ""),
        type=attrs.get("Type", ""),
        nullable=nullable,
        max_length=max_length,
    )


def _parse_key(xml: str) -> List[str]:
    keys: List[str] = []
    for ref in _find_elements(xml, "PropertyRef"):
        name = _get_attr(ref, "Name")
        if name:
            keys.append(name)
    return keys


def _parse_entity_type(xml: str) -> EdmEntityType:
    name = _get_attr(xml, "Name") or ""
    inner = _element_content(xml, "EntityType") or xml
    keys: List[str] = []
    key_el = _find_elements(inner, "Key")
    if key_el:
        keys.extend(_parse_key(key_el[0]))
    properties = [_parse_property(p) for p in _find_elements(inner, "Property")]
    return EdmEntityType(name=name, keys=keys, properties=properties)


def _parse_entity_set(xml: str) -> EdmEntitySet:
    attrs = _get_attrs(xml)
    return EdmEntitySet(name=attrs.get("Name", ""), entity_type=attrs.get("EntityType", ""))


def _parse_action(xml: str) -> EdmAction:
    name = _get_attr(xml, "Name") or ""
    attrs = _get_attrs(xml)
    is_bound = attrs.get("IsBound") == "true"
    inner = _element_content(xml, "Action") or xml
    parameter_type = None
    return_type = None
    for p in _find_elements(inner, "Parameter"):
        p_attrs = _get_attrs(p)
        pname = p_attrs.get("Name", "")
        if pname == "parameter":
            parameter_type = p_attrs.get("Type")
        elif pname == "scriptResult":
            return_type = p_attrs.get("Type")
    return EdmAction(
        name=name,
        is_bound=is_bound,
        parameter_type=parameter_type,
        return_type=return_type,
    )


def _parse_namespace(xml: str) -> str:
    m = re.search(r'<Schema\s+Namespace="([^"]*)"', xml, re.I)
    return m.group(1) if m else ""


def parse_metadata(xml: str) -> ODataMetadata:
    """Parse a $metadata XML string into an :class:`ODataMetadata`."""
    namespace = _parse_namespace(xml)
    entity_types = [_parse_entity_type(e) for e in _find_elements(xml, "EntityType")]
    entity_sets = [_parse_entity_set(e) for e in _find_elements(xml, "EntitySet")]
    actions = [_parse_action(a) for a in _find_elements(xml, "Action")]
    server_version = parse_server_version(xml)
    product_version = server_version.raw if server_version else None
    return ODataMetadata(
        namespace=namespace,
        entity_types=entity_types,
        entity_sets=entity_sets,
        actions=actions,
        enum_types=[],
        raw=xml,
        product_version=product_version,
        server_version=server_version.raw if server_version else None,
    )


class MetadataFetcher:
    """Fetches and caches the OData CSDL $metadata document."""

    def __init__(self, ctx: Any, base_url: str) -> None:
        self._ctx = ctx
        self._base_url = base_url
        self._cache: Optional[ODataMetadata] = None
        self._raw_cache: Optional[str] = None

    def fetch(self, opts: Optional[MetadataOptions] = None) -> ODataMetadata:
        """Fetch and parse $metadata. Results are cached; ``refresh`` forces refetch."""
        opts = opts or MetadataOptions()
        if self._cache is not None and not opts.refresh:
            return self._cache
        xml = self._fetch_xml()
        self._raw_cache = xml
        self._cache = parse_metadata(xml)
        return self._cache

    def fetch_xml(self, opts: Optional[MetadataOptions] = None) -> str:
        """Fetch the raw $metadata XML (escape hatch for debugging)."""
        opts = opts or MetadataOptions()
        if self._raw_cache is not None and not opts.refresh:
            return self._raw_cache
        self._raw_cache = self._fetch_xml()
        # Don't populate the parsed cache here -- it will be parsed on demand.
        return self._raw_cache

    def _fetch_xml(self) -> str:
        res = execute_request(
            self._ctx,
            f"{self._base_url}/$metadata",
            HttpRequestOptions(method="GET", accept="xml"),
        )
        return res.text
