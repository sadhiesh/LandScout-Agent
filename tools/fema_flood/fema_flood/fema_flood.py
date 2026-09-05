"""
FEMA NFHL flood zone lookup from parcel geometry.

Queries the FEMA National Flood Hazard Layer (NFHL) ArcGIS MapServer to determine
flood risk for a given parcel polygon. Uses server-side reprojection (inSR/outSR)
and shapely for area-ratio-based affected acreage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from shapely.geometry import Polygon, shape

logger = logging.getLogger(__name__)

# NFHL base URL (updated 2026-09-01: service moved from /gis/nfhl/rest to /arcgis/rest)
NFHL_BASE = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"

# NFHL layers (vocabulary SSOT)
NFHL_LAYERS = {
    28: "Flood Hazard Zones",  # FLD_ZONE, ZONE_SUBTY='FLOODWAY', SFHA_TF, STATIC_BFE
    3: "FIRM Panels",          # FIRM_PAN, EFF_DATE
    1: "LOMRs",                # CASE_NO, EFF_DATE, STATUS
    34: "LOMAs",               # CASENUMBER, DETERMINATIONTYPE, OUTCOME
}

# Sentinel value for "no data"
NO_DATA_SENTINEL = -9999

# Flood zone risk tiers (highest to lowest)
ZONE_RISK_ORDER = [
    "VE", "V", "AE", "AO", "AH", "A", "A99", "AR",
    "X (shaded)", "X (unshaded)", "AREA NOT INCLUDED", "OPEN WATER", "D",
]


class FEMAFloodError(Exception):
    """FEMA NFHL query error."""
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
        FEMAFloodError: If no WKID can be determined
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
    
    raise FEMAFloodError(
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
        url: Full layer URL (e.g., NFHL_BASE/28)
        rings: Polygon rings [[x,y], ...]
        wkid: Spatial reference WKID for inSR and outSR
        return_geometry: Whether to return feature geometries
        
    Returns:
        Parsed JSON response
        
    Raises:
        FEMAFloodError: On HTTP error or ArcGIS error response
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
        raise FEMAFloodError(f"HTTP error querying {url}: {e}") from e
    except Exception as e:
        raise FEMAFloodError(f"Failed to query {url}: {e}") from e
    
    # ArcGIS returns HTTP 200 with {"error": {...}} on bad queries
    if "error" in data:
        err_msg = data["error"].get("message", "Unknown error")
        raise FEMAFloodError(f"ArcGIS error from {url}: {err_msg}")
    
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
        # TODO: handle holes if needed (interior rings)
        if not parcel_poly.is_valid:
            parcel_poly = parcel_poly.buffer(0)  # Fix self-intersections
    except Exception as e:
        logger.warning(f"Failed to build parcel polygon: {e}")
        # Return features with zero fractions
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


def get_fema_flood_from_geometry(
    geometry: dict[str, Any],
    wkid: int | None = None,
    parcel_acres: float | None = None,
) -> dict[str, Any]:
    """
    Query FEMA NFHL for flood risk on a parcel geometry.
    
    Args:
        geometry: Dict with 'rings' and optional 'spatialReference'
        wkid: Explicit WKID override if geometry lacks spatialReference
        parcel_acres: Optional parcel acreage for affected_acres calculation
        
    Returns:
        Dict with in_flood_zone, details (zones, sfha, floodway, bfe, firm_panel,
        lomrs, lomas, coverage), and investment_impact
        
    Raises:
        FEMAFloodError: On query failure
    """
    # Resolve WKID
    resolved_wkid = _resolve_wkid(geometry, wkid)
    rings = geometry.get("rings")
    if not rings:
        raise FEMAFloodError("Geometry has no 'rings' key")
    
    logger.info(f"Querying FEMA NFHL with WKID {resolved_wkid}")
    
    # Query layer 28: Flood Hazard Zones
    zones_url = f"{NFHL_BASE}/28"
    zones_resp = _intersect_query(zones_url, rings, resolved_wkid, return_geometry=True)
    zone_features = zones_resp.get("features", [])
    
    # Query layer 3: FIRM Panels
    firm_url = f"{NFHL_BASE}/3"
    firm_resp = _intersect_query(firm_url, rings, resolved_wkid, return_geometry=False)
    firm_features = firm_resp.get("features", [])
    
    # Query layer 1: LOMRs
    lomr_url = f"{NFHL_BASE}/1"
    lomr_resp = _intersect_query(lomr_url, rings, resolved_wkid, return_geometry=False)
    lomr_features = lomr_resp.get("features", [])
    
    # Query layer 34: LOMAs
    loma_url = f"{NFHL_BASE}/34"
    loma_resp = _intersect_query(loma_url, rings, resolved_wkid, return_geometry=False)
    loma_features = loma_resp.get("features", [])
    
    # Compute overlaps
    zone_features = _overlap_fractions(rings, zone_features, parcel_acres)
    
    # Extract zone details
    all_zones = []
    raw_zones = []
    sfha = False
    floodway = False
    static_bfe = None
    
    for feat in zone_features:
        attrs = feat.get("attributes", {})
        zone = attrs.get("FLD_ZONE", "Unknown")
        zone_subty = attrs.get("ZONE_SUBTY")
        sfha_tf = attrs.get("SFHA_TF", "").upper()
        bfe = _clean(attrs.get("STATIC_BFE"))
        
        all_zones.append(zone)
        
        if sfha_tf in ("T", "TRUE", "Y", "YES"):
            sfha = True
        
        if zone_subty and zone_subty.upper() == "FLOODWAY":
            floodway = True
        
        if bfe is not None and (static_bfe is None or bfe > static_bfe):
            static_bfe = bfe
        
        raw_zones.append({
            "layer": "Flood Hazard Zones",
            "zone": zone,
            "zone_subtype": zone_subty,
            "sfha": sfha_tf in ("T", "TRUE", "Y", "YES"),
            "bfe": bfe,
            "affected_fraction": feat["affected_fraction"],
            "affected_acres": feat["affected_acres"],
        })
    
    # Unique zones
    all_zones = sorted(set(all_zones))
    worst_zone = _determine_worst_zone(all_zones)
    
    # FIRM panel
    firm_panel = None
    if firm_features:
        firm_panel = firm_features[0].get("attributes", {}).get("FIRM_PAN")
    
    # LOMRs
    lomrs = []
    for feat in lomr_features:
        attrs = feat.get("attributes", {})
        lomrs.append({
            "case_no": attrs.get("CASE_NO"),
            "eff_date": attrs.get("EFF_DATE"),
            "status": attrs.get("STATUS"),
        })
    
    # LOMAs
    lomas = []
    for feat in loma_features:
        attrs = feat.get("attributes", {})
        lomas.append({
            "case_number": attrs.get("CASENUMBER"),
            "determination_type": attrs.get("DETERMINATIONTYPE"),
            "outcome": attrs.get("OUTCOME"),
        })
    
    # Aggregate coverage
    total_fraction = sum(f["affected_fraction"] for f in zone_features)
    total_acres = (
        round(total_fraction * parcel_acres, 2) if parcel_acres else None
    )
    
    # Determine investment impact (placeholder - will be driven by criteria.yaml)
    in_flood_zone = len(zone_features) > 0
    risk_tier = "none"
    discount = 0.0
    explanation = "No flood zone overlap."
    
    if floodway:
        risk_tier = "high"
        discount = 1.0  # 100% discount for floodway
        explanation = "Parcel intersects FEMA floodway - very high flood risk."
    elif worst_zone and worst_zone in ("VE", "V", "AE", "AO", "AH", "A"):
        risk_tier = "high"
        discount = 0.5  # 50% discount for high-risk zones
        explanation = f"Parcel in high-risk flood zone {worst_zone}."
    elif worst_zone and "X" in worst_zone.upper():
        risk_tier = "low"
        discount = 0.1  # 10% discount for shaded X
        explanation = f"Parcel in low-risk flood zone {worst_zone}."
    
    return {
        "in_flood_zone": in_flood_zone,
        "details": {
            "worst_zone": worst_zone,
            "all_zones": all_zones,
            "sfha": sfha,
            "floodway": floodway,
            "static_bfe": static_bfe,
            "firm_panel": firm_panel,
            "lomrs": lomrs,
            "lomas": lomas,
            "coverage": {
                "affected_fraction": round(total_fraction, 4),
                "affected_acres": total_acres,
            },
            "raw": raw_zones,
        },
        "investment_impact": {
            "risk_tier": risk_tier,
            "usable_acres_discount": discount,
            "explanation": explanation,
        },
    }


def run_fema_flood_check(**kwargs) -> str:
    """
    Agent wrapper for get_fema_flood_from_geometry.
    
    Returns JSON string, never raises.
    """
    try:
        result = get_fema_flood_from_geometry(**kwargs)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.exception("FEMA flood check failed")
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
        """Check FEMA flood risk for a parcel geometry."""
        try:
            geom = json.loads(geometry)
            result = get_fema_flood_from_geometry(geom, wkid=wkid, parcel_acres=acres)
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            raise typer.Exit(1)
    
    app()
