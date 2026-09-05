"""CAD parcel enrichment with county routing.

Routes to county-specific CAD implementations. Collin County is live via
ArcGIS; others return not_implemented.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.enrichment.registry import register

logger = logging.getLogger(__name__)


def _normalize_county(county: str) -> str:
    """Normalize a county name to a routing key.

    Handles the shapes that reach us from different sources: "Collin",
    "Collin County", and "Collin County, TX". Anything after a comma is a
    state qualifier rather than part of the name, so it is dropped before the
    "county" suffix is stripped — otherwise the state would survive into the
    key and silently miss CAD_BY_COUNTY.
    """
    name = county.lower().split(",")[0].strip()
    return name.removesuffix(" county").strip()


def _attach_neighborhood_comps(result: dict[str, Any]) -> None:
    """Add a neighborhood comp cohort to a successful lookup, in place.

    The subject's own appraised value says nothing about whether it is dear or
    cheap; the cohort median does. A comps failure is logged and the key left
    absent — the scorer falls back to the subject's own valuation.
    """
    from collin_cad import get_neighborhood_comps

    parcel = result.get("parcel")
    if not parcel:
        return

    status = parcel.get("status") or {}
    nbhd_code = status.get("nbhdCode")
    if not nbhd_code:
        logger.info("No nbhdCode on parcel; skipping neighborhood comps")
        return

    land = parcel.get("land") or {}
    try:
        result["neighborhood_comps"] = get_neighborhood_comps(
            nbhd_code=nbhd_code,
            land_type_code=land.get("landTypeCode"),
        )
    except Exception as e:
        logger.warning(f"Neighborhood comps failed for {nbhd_code}: {e}")


def _collin_lookup(parcel: dict[str, Any]) -> dict[str, Any]:
    """Lookup Collin County parcel data via CCAD ArcGIS."""
    try:
        from collin_cad import get_collin_parcel_data, CollinCADError
    except ImportError:
        logger.error("collin_cad not installed")
        return {"status": "error", "message": "collin_cad package not available"}
    
    # Try nested structure (normalized) first, then flat fallback
    location = parcel.get("location", {})
    basic_info = parcel.get("basic_info", {})
    
    latitude = location.get("lat") or parcel.get("latitude")
    longitude = location.get("lon") or parcel.get("longitude")
    address = basic_info.get("address") or parcel.get("address")
    city = location.get("city") or parcel.get("city")
    
    try:
        if latitude and longitude:
            result = get_collin_parcel_data(latitude=latitude, longitude=longitude)
        elif address:
            result = get_collin_parcel_data(address=address, city=city)
        else:
            return {
                "status": "error",
                "message": "No latitude/longitude or address for CAD lookup"
            }
        
        _attach_neighborhood_comps(result)
        return result
    
    except CollinCADError as e:
        logger.warning(f"Collin CAD lookup failed: {e}")
        return {"status": "error", "message": str(e)}


def _not_implemented_stub(county: str) -> dict[str, Any]:
    """Stub for counties without CAD implementation."""
    return {
        "status": "not_implemented",
        "county": county,
        "note": "Only Collin County, Texas is currently supported for detailed parcel data (CAD lookup, geometry, valuation)",
    }


# County routing map
CAD_BY_COUNTY = {
    "collin": _collin_lookup,
}


@register("cad_parcel", enabled=True)
def enrich_cad_parcel(parcel: dict[str, Any]) -> dict[str, Any]:
    """Enrich parcel with county CAD data (geometry, valuation, ownership).
    
    Routes by county field (looks in location.county first, then flat county).
    Collin County uses CCAD ArcGIS; other counties return not_implemented.
    """
    # Try nested structure first (normalized), then flat fallback
    location = parcel.get("location", {})
    county_raw = location.get("county") or parcel.get("county")
    
    if not county_raw:
        return {"status": "error", "message": "No county field in parcel"}
    
    county = _normalize_county(county_raw)
    
    # Route to county implementation
    lookup_fn = CAD_BY_COUNTY.get(county)
    
    if lookup_fn:
        logger.info(f"CAD lookup: {county} (implemented)")
        return lookup_fn(parcel)
    else:
        logger.info(f"CAD lookup: {county} (not implemented)")
        return _not_implemented_stub(county_raw)
