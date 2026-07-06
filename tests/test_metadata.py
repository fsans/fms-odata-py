"""Tests for $metadata parsing and version detection.

Ports ``tests/unit/metadata.test.ts`` and the version-detection section of
``tests/unit/client.test.ts`` from fms-odata-js.
"""

from __future__ import annotations

import httpx
import pytest

from fms_odata.metadata import parse_metadata

from .conftest import make_client, text_response

SAMPLE_METADATA = """<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="FMI" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="contact">
        <Key>
          <PropertyRef Name="id" />
        </Key>
        <Property Name="id" Type="Edm.Int64" Nullable="false" />
        <Property Name="firstName" Type="Edm.String" MaxLength="100" />
        <Property Name="lastName" Type="Edm.String" MaxLength="100" />
        <Property Name="email" Type="Edm.String" MaxLength="255" />
        <Property Name="createdAt" Type="Edm.DateTimeOffset" />
        <Property Name="isActive" Type="Edm.Boolean" />
        <NavigationProperty Name="addresses" Type="Collection(FMI.address)" />
      </EntityType>
      <EntityType Name="address">
        <Key>
          <PropertyRef Name="id" />
        </Key>
        <Property Name="id" Type="Edm.Int64" Nullable="false" />
        <Property Name="street" Type="Edm.String" MaxLength="200" />
        <Property Name="city" Type="Edm.String" MaxLength="100" />
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="contact" EntityType="FMI.contact" />
        <EntitySet Name="address" EntityType="FMI.address" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


def metadata_with_version(version):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="FMI" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityContainer Name="Container">
        <Annotation Term="Org.OData.Core.V1.ProductVersion" String="{version}" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


METADATA_NO_VERSION = """<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="FMI" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityContainer Name="Container" />
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


def make_metadata_client(xml):
    return make_client(lambda req: text_response(xml, headers={"content-type": "application/xml"}))


# -- parse_metadata ---------------------------------------------------------


def test_parse_metadata_extracts_entity_types_and_sets():
    meta = parse_metadata(SAMPLE_METADATA)
    assert meta.namespace == "FMI"
    names = {et.name for et in meta.entity_types}
    assert names == {"contact", "address"}
    set_names = {es.name for es in meta.entity_sets}
    assert set_names == {"contact", "address"}


def test_parse_metadata_extracts_keys_and_properties():
    meta = parse_metadata(SAMPLE_METADATA)
    contact = next(et for et in meta.entity_types if et.name == "contact")
    assert contact.keys == ["id"]
    prop_names = {p.name for p in contact.properties}
    assert {"id", "firstName", "lastName", "email", "createdAt", "isActive"} <= prop_names


# -- version detection ------------------------------------------------------


def test_detects_version_20():
    db = make_metadata_client(metadata_with_version("20.0.1"))
    assert db.version() == "20"
    db.close()


def test_detects_version_21():
    db = make_metadata_client(metadata_with_version("21.1.2"))
    assert db.version() == "21"
    db.close()


def test_detects_version_22():
    db = make_metadata_client(metadata_with_version("22.0.1"))
    assert db.version() == "22"
    db.close()


def test_detects_version_26():
    db = make_metadata_client(metadata_with_version("26.0.0"))
    assert db.version() == "26"
    db.close()


def test_returns_future_for_unknown_newer_versions():
    db = make_metadata_client(metadata_with_version("99.0.0"))
    assert db.version() == "future"
    db.close()


def test_returns_none_when_product_version_absent():
    db = make_metadata_client(METADATA_NO_VERSION)
    assert db.version() is None
    db.close()


def test_caches_detected_version_across_calls():
    call_count = {"n": 0}

    def handler(req):
        call_count["n"] += 1
        return text_response(
            metadata_with_version("22.0.1"), headers={"content-type": "application/xml"}
        )

    db = make_client(handler)
    assert db.version() == "22"
    assert db.version() == "22"
    assert db.version() == "22"
    # $metadata should only be fetched once (cached)
    assert call_count["n"] == 1
    db.close()


# -- version_info / has_feature ---------------------------------------------


def test_version_info_returns_full_info():
    db = make_metadata_client(metadata_with_version("26.0.0"))
    info = db.version_info()
    assert info is not None
    assert info.major == "26"
    assert info.name == "Claris FileMaker 2026"
    assert info.features.scripts_by_fmsid is True
    assert info.features.apply_aggregation is True
    db.close()


def test_version_info_none_when_undetermined():
    db = make_metadata_client(METADATA_NO_VERSION)
    assert db.version_info() is None
    db.close()


def test_has_feature_true_for_supported():
    db = make_metadata_client(metadata_with_version("22.0.1"))
    assert db.has_feature("apply_aggregation") is True
    assert db.has_feature("webhooks") is True
    db.close()


def test_has_feature_false_for_unsupported():
    db = make_metadata_client(metadata_with_version("20.0.1"))
    assert db.has_feature("apply_aggregation") is False
    assert db.has_feature("webhooks") is False
    assert db.has_feature("scripts_by_fmsid") is False
    db.close()


def test_has_feature_false_when_undetermined():
    db = make_metadata_client(METADATA_NO_VERSION)
    assert db.has_feature("apply_aggregation") is False
    db.close()
