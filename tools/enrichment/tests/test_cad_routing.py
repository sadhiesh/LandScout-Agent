"""Tests for enrichment registry and CAD routing."""

from __future__ import annotations

import pytest

from tools.enrichment import REGISTRY, get_enabled_enrichers
from tools.enrichment.cad_parcel import (
    CAD_BY_COUNTY,
    _normalize_county,
    enrich_cad_parcel,
)


def test_cad_parcel_registered():
    """Test that cad_parcel enricher is registered and enabled."""
    enrichers = {e.name: e for e in REGISTRY}
    assert "cad_parcel" in enrichers
    assert enrichers["cad_parcel"].enabled is True


def test_collin_routing_normalized_structure():
    """Test that Collin County routing works with normalized nested structure."""
    parcel = {
        "property_id": 12345,
        "location": {
            "county": "Collin",
            "state": "TX",
            "lat": 33.1581,
            "lon": -96.6397,
        },
        "basic_info": {
            "title": "Test Property",
            "acres": 10.5,
            "price": 250000,
        }
    }
    
    # This will call _collin_lookup which will fail to import collin_cad
    # but we can check that it attempted Collin routing
    result = enrich_cad_parcel(parcel)
    
    # Should get an error about collin_cad not being installed OR
    # an actual result if the package is available
    assert "status" in result
    # Either "error" from missing package or actual CAD data
    assert result["status"] in ("error", "success", "not_found")


def test_collin_routing_flat_fallback():
    """Test that Collin County routing falls back to flat county field."""
    parcel = {
        "property_id": 12345,
        "county": "Collin County, TX",  # Flat structure with extra text
        "latitude": 33.1581,
        "longitude": -96.6397,
        "title": "Test Property",
    }
    
    result = enrich_cad_parcel(parcel)
    
    # Should normalize "Collin County, TX" to "collin" and route correctly
    assert "status" in result
    assert result["status"] in ("error", "success", "not_found")


def test_non_collin_county_returns_not_implemented():
    """Test that non-Collin counties return not_implemented status."""
    parcel = {
        "property_id": 67890,
        "location": {
            "county": "Dallas",
            "state": "TX",
        },
        "basic_info": {
            "title": "Dallas Property",
        }
    }
    
    result = enrich_cad_parcel(parcel)
    
    assert result["status"] == "not_implemented"
    # The note is a generic capability message; the county comes back on its
    # own key so the caller can see which one was skipped.
    assert result["county"] == "Dallas"


def test_missing_county_returns_error():
    """Test that parcels without county field return error status."""
    parcel = {
        "property_id": 99999,
        "location": {
            "state": "TX",
        },
        "basic_info": {
            "title": "No County Property",
        }
    }
    
    result = enrich_cad_parcel(parcel)
    
    assert result["status"] == "error"
    assert "No county" in result["message"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Collin", "collin"),
        ("Collin County", "collin"),
        ("collin county", "collin"),
        ("  Collin County  ", "collin"),
        ("Collin County, TX", "collin"),
        ("collin county, texas", "collin"),
        ("Dallas", "dallas"),
    ],
)
def test_normalize_county_strips_suffix_and_state(raw: str, expected: str) -> None:
    assert _normalize_county(raw) == expected


@pytest.mark.parametrize(
    "raw", ["Collin", "Collin County", "Collin County, TX", "collin county, texas"]
)
def test_every_collin_spelling_routes_to_cad(raw: str) -> None:
    """A state suffix must not silently drop CAD lookup.

    CAD supplies the geometry the flood enrichers read, so a county string
    that misses this map disables the whole enrichment chain without an error.
    """
    assert _normalize_county(raw) in CAD_BY_COUNTY


def test_cad_parcel_in_enabled_enrichers():
    """Test that cad_parcel appears in get_enabled_enrichers()."""
    enabled = get_enabled_enrichers()
    enabled_names = [e.name for e in enabled]
    
    assert "cad_parcel" in enabled_names
