"""Flood zone enricher using FEMA NFHL and Collin County floodplain tools.

Queries both FEMA National Flood Hazard Layer and Collin County Bo4 layer
to determine flood risk for a parcel. Uses the parcel geometry from Collin CAD.

Enabled per ADR 0014.
"""

from __future__ import annotations

import logging
from typing import Any

from fema_flood import get_fema_flood_from_geometry
from collin_flood import get_collin_floodplain_from_geometry

from .registry import register

logger = logging.getLogger(__name__)


@register("flood_fema", enabled=True)
def enrich_flood_fema(parcel: dict[str, Any]) -> dict[str, Any]:
    """Enrich parcel with FEMA and Collin County flood zone data.
    
    Args:
        parcel: Parcel data including geometry from Collin CAD
        
    Returns:
        Dict with fema_flood and collin_flood keys, each containing
        flood risk details and investment impact
    """
    # Look for geometry in multiple locations:
    # 1. Top-level (if passed directly)
    # 2. CAD enrichment (from cad_parcel enricher)
    geometry = parcel.get("geometry")
    
    if not geometry:
        # Check if cad_parcel enrichment has geometry
        enrichment = parcel.get("enrichment", {})
        cad_data = enrichment.get("cad_parcel", {})
        if cad_data and isinstance(cad_data, dict):
            # CAD enricher returns {"parcel": {...}, "matches": [], "warnings": []}
            cad_parcel = cad_data.get("parcel", {})
            geometry = cad_parcel.get("geometry")
    
    if not geometry:
        logger.warning("No geometry in parcel or CAD enrichment; cannot check flood status")
        return {
            "fema_flood": None,
            "collin_flood": None,
            "error": "No geometry available for flood check",
        }
    
    # Get parcel acreage for affected_acres calculation
    land = parcel.get("land", {})
    parcel_acres = land.get("landSizeAcres") or parcel.get("gis_acres")
    
    result = {}
    
    # Query FEMA NFHL
    try:
        fema_result = get_fema_flood_from_geometry(
            geometry, parcel_acres=parcel_acres
        )
        result["fema_flood"] = fema_result
        logger.info(f"FEMA flood check: in_flood_zone={fema_result['in_flood_zone']}")
    except Exception as e:
        logger.error(f"FEMA flood check failed: {type(e).__name__}: {e}")
        result["fema_flood"] = {"error": str(e)}
    
    # Query Collin County floodplain
    try:
        collin_result = get_collin_floodplain_from_geometry(
            geometry, parcel_acres=parcel_acres
        )
        result["collin_flood"] = collin_result
        logger.info(f"Collin flood check: floodplain={collin_result['floodplain']}")
    except Exception as e:
        logger.error(f"Collin flood check failed: {type(e).__name__}: {e}")
        result["collin_flood"] = {"error": str(e)}
    
    return result
