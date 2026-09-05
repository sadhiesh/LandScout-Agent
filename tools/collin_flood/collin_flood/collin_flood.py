"""
Collin County floodplain lookup from parcel geometry.

Queries the Collin County Bo4 FeatureServer to determine floodplain status for
a given parcel polygon. Uses server-side reprojection (inSR/outSR) and shapely
for area-ratio-based affected acreage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from shapely.geometry import Polygon

logger = logging.getLogger(__name__)

# Collin County floodplain service (updated 2026-09-01: service moved from services2 to services9)
COLLIN_FLOOD_URL = "https://services9.arcgis.com/8qadn7hfDj86yxAd/arcgis/rest/services/Collin_County_Flood__Bo4_/FeatureServer/0"

# Sentinel value for "no data"
NO_DATA_SENTINEL = -9999

# Flood zone risk tiers (highest to lowest)
ZONE_RISK_ORDER = [
    "AE", "AO", "AH", "A", "A99", "AR",
    "X (shaded)", "X (unshaded)", "AREA NOT INCLUDED",
]


class CollinFloodError(Exception):
    """Collin County floodplain query error."""
    pass


def _resolve_wkid(geometry: dict[str, Any], wkid: int | None) -> int:
    """
    Extract WKID from geometry's spatialReference or use explicit override.
    
    Args:
        geometry: GeoJSON-like dict with optional spatialReference key
        wkid: Explicit WKID override
        
    Returns:
        WKID as integer
        
    Raises:
        CollinFloodError: If no WKID can be determined
    """
    # Check geometry's embedded spatialReference
    if "spatialReference" in geometry:
        sr = geometry["spatialReference"]
        if "wkid" in sr:
            return int(sr["wkid"])
        if "latestWkid" in sr:
            return int(sr["latestWkid"])
    
    # Fall back to explicit parameter
    if wkid is not None:
        return int(wkid)
    
    raise CollinFloodError(
        "Cannot determine spatial reference: geometry has no spatialReference "
        "and no wkid parameter provided"
    )


def _intersect_query(
    url: str,
    rings: list[list[list[float]]],
    wkid: int,
    return_geometry: bool = True,
) -> dict[str, Any]:
    """
    Query ArcGIS FeatureServer with polygon intersection.
    
    Args:
        url: Full layer URL
        rings: Polygon rings [[x,y], ...]
        wkid: Spatial reference WKID for inSR and outSR
        return_geometry: Whether to return feature geometries
        
    Returns:
        Parsed JSON response
        
    Raises:
        CollinFloodError: On HTTP error or ArcGIS error response
    """
    geometry_json = json.dumps({"rings": rings, "spatialReference": {"wkid": wkid}})
    
    params = {
        "geometry": geometry_json,
        "geometryType": "esriGeometryPolygon",
        "inSR": str(wkid),
        "outSR": str(wkid),
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "true" if return_geometry else "false",
        "outFields": "*",
        "f": "json",
    }
    
    try:
        resp = httpx.get(url + "/query", params=params, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise CollinFloodError(f"HTTP error querying {url}: {e}") from e
    except Exception as e:
        raise CollinFloodError(f"Failed to query {url}: {e}") from e
    
    # ArcGIS returns HTTP 200 with {"error": {...}} on bad queries
    if "error" in data:
        err_msg = data["error"].get("message", "Unknown error")
        raise CollinFloodError(f"ArcGIS error from {url}: {err_msg}")
    
    return data


def _clean(value: Any) -> Any:
    """Normalize -9999 sentinel to None."""
    if value == NO_DATA_SENTINEL:
        return None
    return value


def _overlap_fractions(
    parcel_rings: list[list[list[float]]],
    features: list[dict[str, Any]],
    parcel_acres: float | None,
) -> list[dict[str, Any]]:
    """
    Compute area-ratio-based overlap fractions for each feature.
    
    Args:
        parcel_rings: Parcel polygon rings
        features: List of intersecting features with geometry.rings
        parcel_acres: Optional parcel acreage from CAD
        
    Returns:
        List of features with added affected_fraction and affected_acres
    """
    # Build parcel polygon
    try:
        parcel_poly = Polygon(parcel_rings[0])  # Exterior ring
        if not parcel_poly.is_valid:
            parcel_poly = parcel_poly.buffer(0)  # Fix self-intersections
    except Exception as e:
        logger.warning(f"Failed to build parcel polygon: {e}")
        for f in features:
            f["affected_fraction"] = 0.0
            f["affected_acres"] = None
        return features
    
    parcel_area = parcel_poly.area
    if parcel_area == 0:
        for f in features:
            f["affected_fraction"] = 0.0
            f["affected_acres"] = None
        return features
    
    # Compute overlap for each feature
    results = []
    for feat in features:
        try:
            geom = feat.get("geometry", {})
            if "rings" not in geom:
                feat["affected_fraction"] = 0.0
                feat["affected_acres"] = None
                results.append(feat)
                continue
            
            flood_poly = Polygon(geom["rings"][0])
            if not flood_poly.is_valid:
                flood_poly = flood_poly.buffer(0)
            
            intersection = parcel_poly.intersection(flood_poly)
            overlap_area = intersection.area
            fraction = overlap_area / parcel_area
            
            feat["affected_fraction"] = round(fraction, 4)
            feat["affected_acres"] = (
                round(fraction * parcel_acres, 2) if parcel_acres else None
            )
        except Exception as e:
            logger.warning(f"Failed to compute overlap for feature: {e}")
            feat["affected_fraction"] = 0.0
            feat["affected_acres"] = None
        
        results.append(feat)
    
    return results


def _determine_worst_zone(zones: list[str]) -> str | None:
    """Return the highest-risk zone from a list."""
    if not zones:
        return None
    
    # Find first zone in ZONE_RISK_ORDER that appears in zones
    for risk_zone in ZONE_RISK_ORDER:
        for z in zones:
            if z.upper().startswith(risk_zone.upper()):
                return z
    
    # Return first zone if no match in priority order
    return zones[0]


def get_collin_floodplain_from_geometry(
    geometry: dict[str, Any],
    wkid: int | None = None,
    parcel_acres: float | None = None,
) -> dict[str, Any]:
    """
    Query Collin County Bo4 layer for floodplain status on a parcel geometry.
    
    Args:
        geometry: Dict with 'rings' and optional 'spatialReference'
        wkid: Explicit WKID override if geometry lacks spatialReference
        parcel_acres: Optional parcel acreage for affected_acres calculation
        
    Returns:
        Dict with floodplain (bool), details (flood_zone, all_zones, sfha,
        floodway, bfe, firm_panel=None, coverage, raw)
        
    Raises:
        CollinFloodError: On query failure
    """
    # Resolve WKID
    resolved_wkid = _resolve_wkid(geometry, wkid)
    rings = geometry.get("rings")
    if not rings:
        raise CollinFloodError("Geometry has no 'rings' key")
    
    logger.info(f"Querying Collin County floodplain with WKID {resolved_wkid}")
    
    # Query Bo4 layer 0
    flood_resp = _intersect_query(COLLIN_FLOOD_URL, rings, resolved_wkid, return_geometry=True)
    flood_features = flood_resp.get("features", [])
    
    # If no features, return floodplain: false
    if not flood_features:
        return {
            "floodplain": False,
            "details": {
                "flood_zone": None,
                "all_zones": [],
                "sfha": False,
                "floodway": False,
                "bfe": None,
                "firm_panel": None,
                "coverage": {
                    "affected_fraction": 0.0,
                    "affected_acres": None,
                },
                "raw": [],
            },
        }
    
    # Compute overlaps
    flood_features = _overlap_fractions(rings, flood_features, parcel_acres)
    
    # Extract zone details
    all_zones = []
    raw_zones = []
    sfha = False
    floodway = False
    bfe = None
    
    for feat in flood_features:
        attrs = feat.get("attributes", {})
        zone = attrs.get("FLD_ZONE", "Unknown")
        floodway_flag = attrs.get("FLOODWAY", "").upper()
        sfha_tf = attrs.get("SFHA_TF", "").upper()
        static_bfe = _clean(attrs.get("STATIC_BFE"))
        
        all_zones.append(zone)
        
        if sfha_tf in ("T", "TRUE", "Y", "YES"):
            sfha = True
        
        if floodway_flag in ("Y", "YES", "TRUE", "T"):
            floodway = True
        
        if static_bfe is not None and (bfe is None or static_bfe > bfe):
            bfe = static_bfe
        
        raw_zones.append({
            "zone": zone,
            "floodway": floodway_flag in ("Y", "YES", "TRUE", "T"),
            "sfha": sfha_tf in ("T", "TRUE", "Y", "YES"),
            "bfe": static_bfe,
            "affected_fraction": feat["affected_fraction"],
            "affected_acres": feat["affected_acres"],
        })
    
    # Unique zones
    all_zones = sorted(set(all_zones))
    worst_zone = _determine_worst_zone(all_zones)
    
    # Aggregate coverage
    total_fraction = sum(f["affected_fraction"] for f in flood_features)
    total_acres = (
        round(total_fraction * parcel_acres, 2) if parcel_acres else None
    )
    
    return {
        "floodplain": True,
        "details": {
            "flood_zone": worst_zone,
            "all_zones": all_zones,
            "sfha": sfha,
            "floodway": floodway,
            "bfe": bfe,
            "firm_panel": None,  # Bo4 layer has no FIRM panel field
            "coverage": {
                "affected_fraction": round(total_fraction, 4),
                "affected_acres": total_acres,
            },
            "raw": raw_zones,
        },
    }


def run_collin_floodplain_check(**kwargs) -> str:
    """
    Agent wrapper for get_collin_floodplain_from_geometry.
    
    Returns JSON string, never raises.
    """
    try:
        result = get_collin_floodplain_from_geometry(**kwargs)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.exception("Collin floodplain check failed")
        return json.dumps({"error": str(e)})


# CLI
if __name__ == "__main__":
    import sys
    import typer
    
    app = typer.Typer()
    
    @app.command()
    def check(
        geometry: str = typer.Option(..., help="Geometry JSON string with rings"),
        wkid: int | None = typer.Option(None, help="Spatial reference WKID"),
        acres: float | None = typer.Option(None, help="Parcel acreage"),
    ):
        """Check Collin County floodplain status for a parcel geometry."""
        try:
            geom = json.loads(geometry)
            result = get_collin_floodplain_from_geometry(geom, wkid=wkid, parcel_acres=acres)
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            raise typer.Exit(1)
    
    app()
