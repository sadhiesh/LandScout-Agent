"""Collin Central Appraisal District (CCAD) parcel data client.

Single-file implementation per the brief. Query parcels by property ID, parcel ID,
address, or lat/lon from the official CCAD ArcGIS FeatureServer layer 4.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import datetime
from typing import Any, Optional

import httpx
import typer
from pydantic import BaseModel, ConfigDict, model_validator

logger = logging.getLogger(__name__)

# Service
BASE_URL = "https://services2.arcgis.com/uXyoacYrZTPTKD3R/arcgis/rest/services/CCAD_Parcel_Feature_Set/FeatureServer/4"

# Layer's advertised maxRecordCount. A cohort query returning exactly this many
# rows was truncated, so any median over it is drawn from a partial sample.
MAX_RECORD_COUNT = 2000

# Below this many comparable parcels a median is noise, so it is withheld
# rather than reported with false precision.
MIN_COMP_COHORT = 5

# City codes: entityCityCode -> jurisdiction city
CITY_CODES = {
    "CAL": "Allen",
    "CAN": "Anna",
    "CBL": "Blue Ridge",
    "CCR": "Carrollton",
    "CCL": "Celina",
    "CDA": "Dallas",
    "CFV": "Fairview",
    "CFC": "Farmersville",
    "CFR": "Frisco",
    "CGA": "Garland",
    "CJO": "Josephine",
    "CLA": "Lavon",
    "CLC": "Lowry Crossing",
    "CLU": "Lucas",
    "CMC": "McKinney",
    "CML": "Melissa",
    "CMR": "Murphy",
    "CNV": "Nevada",
    "CNH": "New Hope",
    "CPK": "Parker",
    "CPL": "Plano",
    "CPN": "Princeton",
    "CPR": "Prosper",
    "CRC": "Richardson",
    "CRY": "Royse City",
    "CSA": "Sachse",
    "CSP": "St. Paul",
    "CVA": "Van Alstyne",
    "CWS": "Weston",
    "CWY": "Wylie",
}

# Field groups. Every name here must exist in the layer's attribute bag — a
# typo does not raise, it silently yields a block of nulls.
SITUS_FIELDS = (
    "situsBldgNum", "situsStreetPrefix", "situsStreetName", "situsStreetSuffix",
    "situsUnit", "situsCity", "situsZip", "situsConcat",
)
OWNER_FIELDS = (
    "ownerName", "ownerNameAddtl", "ownerAddrLine1", "ownerAddrLine2",
    "ownerAddrCity", "ownerAddrState", "ownerAddrZip",
)
LEGAL_FIELDS = (
    "legalDescription", "legalAbsSubName", "legalAbsSubBlock", "legalAbsSubLot",
)
LAND_FIELDS = (
    "landSizeAcres", "landAgAcres", "landSizeSqft", "landTypeCode",
    "landCategoryCodes",
)
IMPROVEMENT_FIELDS = (
    "imprvMainArea", "imprvYearBuilt", "imprvClassCd", "imprvPoolFlag",
)
DEED_FIELDS = ("deedEffDate", "deedFileDate", "deedTypeCd", "deedNum")
ENTITY_FIELDS = (
    "entityCodes", "entitySchoolCode", "entityCityCode", "entityMUD",
    "entityTIF", "entitySBCL",
)
STATUS_FIELDS = (
    "nbhdCode", "propSubType", "propCategoryCode", "exemptCodes",
    "exemptHmstdFlag", "protestCode", "udiPropFlag", "propSplitFromPID",
)


class CollinCADError(Exception):
    """Base exception for Collin CAD tool."""


class ParcelNotFound(CollinCADError):
    """No parcel matched the lookup."""


class AmbiguousParcel(CollinCADError):
    """Multiple parcels matched; need more specificity."""


class ParcelLookupInput(BaseModel):
    """Input for Collin CAD parcel lookup. Exactly one lookup method required."""
    
    model_config = ConfigDict(extra="forbid")
    
    property_id: Optional[int] = None
    parcel_id: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    @model_validator(mode='after')
    def validate_exactly_one_method(self):
        """Validate exactly one lookup method is provided."""
        # Gather all non-None lookup fields
        provided = []
        if self.property_id is not None:
            provided.append("property_id")
        if self.parcel_id is not None:
            provided.append("parcel_id")
        if self.address is not None:
            provided.append("address")
        
        # Handle lat/lon as a single method
        has_lat = self.latitude is not None
        has_lon = self.longitude is not None
        
        if has_lat and not has_lon:
            raise ValueError("latitude and longitude must both be provided")
        if has_lon and not has_lat:
            raise ValueError("latitude and longitude must both be provided")
        
        if has_lat and has_lon:
            provided.append("latlon")
        
        if len(provided) == 0:
            raise ValueError("Provide at least one lookup method")
        if len(provided) > 1:
            raise ValueError(f"Provide exactly one lookup method, got: {provided}")
        
        return self


def _sql_quote(s: str) -> str:
    """Quote a string for ArcGIS WHERE clause (double embedded single quotes)."""
    return s.replace("'", "''")


def _epoch_ms_to_iso(ms: Optional[int]) -> Optional[str]:
    """Convert epoch milliseconds to ISO date string."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).date().isoformat()
    except Exception:
        return None


def _valuation_block(attrs: dict[str, Any], prefix: str) -> Optional[dict[str, Any]]:
    """Extract market/land/ag valuation for a prefix (currVal/noticeVal/prevVal)."""
    market = attrs.get(f"{prefix}Market")
    if market is None or market == 0:
        return None
    
    return {
        "market": market,
        "land": attrs.get(f"{prefix}Land"),
        "improvement": attrs.get(f"{prefix}Imprv"),
        "appraised": attrs.get(f"{prefix}Appraised"),
        "assessed": attrs.get(f"{prefix}Assessed"),
        "ag_loss": attrs.get(f"{prefix}AgLoss"),
    }


def _normalize_street(value: Optional[str]) -> str:
    """Collapse a street string to a comparable form: upper case, single spaces."""
    if not value:
        return ""
    return " ".join(str(value).upper().split())


def _situs_street_address(attrs: dict[str, Any]) -> str:
    """Rebuild the situs street line from its parts for owner-address comparison."""
    parts = [
        attrs.get("situsBldgNum"),
        attrs.get("situsStreetPrefix"),
        attrs.get("situsStreetName"),
        attrs.get("situsStreetSuffix"),
    ]
    return _normalize_street(" ".join(str(p) for p in parts if p))


def _compactness(shape_area: Optional[float], shape_length: Optional[float]) -> Optional[float]:
    """Polsby-Popper compactness: 1.0 is a circle, a long thin strip approaches 0.

    A low value means an irregular or elongated tract, which constrains layout
    and frontage far more than acreage alone suggests.
    """
    if not shape_area or not shape_length or shape_length <= 0:
        return None
    return (4 * math.pi * shape_area) / (shape_length ** 2)


def _held_years(deed_eff_ms: Optional[int]) -> Optional[float]:
    """Years since the deed took effect. Resolved here so scoring stays pure."""
    if not deed_eff_ms:
        return None
    try:
        effective = datetime.fromtimestamp(deed_eff_ms / 1000)
    except (OverflowError, OSError, ValueError):
        return None
    return (datetime.now() - effective).days / 365.25


def _shape_parcel(feature: dict[str, Any], spatial_reference: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Shape a raw ArcGIS feature into the output schema."""
    attrs = feature["attributes"]
    geom = feature.get("geometry")
    centroid_geom = feature.get("centroid")
    
    # Attach spatialReference to geometry if provided
    if geom and spatial_reference:
        geom["spatialReference"] = spatial_reference
    
    # City from entityCityCode only
    entity_city_code = attrs.get("entityCityCode")
    city = CITY_CODES.get(entity_city_code, "Unincorporated (Collin County)")
    
    # Valuation: walk currVal -> noticeVal -> prevVal
    prop_year = attrs.get("propYear")
    valuation = None
    basis = None
    year = None
    
    for prefix, b in [("currVal", "current"), ("noticeVal", "notice"), ("prevVal", "previous")]:
        val = _valuation_block(attrs, prefix)
        if val:
            valuation = val
            basis = b
            # For prevVal, year is propYear - 1
            year = (prop_year - 1) if prefix == "prevVal" and prop_year else prop_year
            break
    
    # Centroid
    centroid = None
    if centroid_geom:
        centroid = {"lat": centroid_geom["y"], "lon": centroid_geom["x"]}
    elif geom and geom.get("rings"):
        # Compute centroid from polygon if service didn't return it
        rings = geom["rings"][0] if geom["rings"] else []
        if rings:
            avg_x = sum(p[0] for p in rings) / len(rings)
            avg_y = sum(p[1] for p in rings) / len(rings)
            centroid = {"lat": avg_y, "lon": avg_x}
    
    # GIS acres from shape area (square feet to acres)
    shape_area = attrs.get("Shape__Area")
    gis_acres = (shape_area / 43560) if shape_area else None
    
    # Market per acre
    market_val = valuation["market"] if valuation else None
    land_acres = attrs.get("landSizeAcres")
    market_per_acre = (market_val / land_acres) if market_val and land_acres and land_acres > 0 else None
    land_per_acre = (valuation["land"] / land_acres) if valuation and valuation["land"] and land_acres and land_acres > 0 else None
    
    # AG exempt
    ag_acres = attrs.get("landAgAcres") or 0
    ag_loss = valuation.get("ag_loss") if valuation else 0
    ag_exempt = ag_acres > 0 or (ag_loss and ag_loss > 0)
    
    # Share of market value removed by the ag valuation. This is both the
    # carrying-cost saving today and the rollback exposure on change of use.
    ag_loss_ratio = (ag_loss / market_val) if ag_loss and market_val and market_val > 0 else None
    
    # Improved
    imprv_area = attrs.get("imprvMainArea")
    imprv_year = attrs.get("imprvYearBuilt")
    improved = bool(imprv_area and imprv_area > 0) or bool(imprv_year and imprv_year > 0)
    
    # Appraised acreage against GIS acreage. A wide gap means one of the two
    # is stale, so downstream acreage judgements deserve less confidence.
    acreage_variance = (
        abs(gis_acres - land_acres) / land_acres
        if gis_acres and land_acres and land_acres > 0
        else None
    )
    
    # Owner mailing address on the parcel itself means owner-occupied rather
    # than an absentee holding.
    owner_line1 = _normalize_street(attrs.get("ownerAddrLine1"))
    situs_line = _situs_street_address(attrs)
    owner_occupied = bool(owner_line1 and situs_line and owner_line1 == situs_line)
    
    # Situs
    situs = {
        k: attrs.get(k)
        for k in SITUS_FIELDS
    }
    
    # Owner
    owner = {
        k: attrs.get(k)
        for k in OWNER_FIELDS
    }
    
    # Legal
    legal = {
        k: attrs.get(k)
        for k in LEGAL_FIELDS
    }
    
    return {
        "parcel_id": attrs.get("geoID"),
        "property_id": attrs.get("PROP_ID"),
        "centroid": centroid,
        "geometry": geom,
        "gis_acres": gis_acres,
        "city": city,
        "situs": situs,
        "owner": owner,
        "legal": legal,
        "valuation": valuation,
        "valuation_year": year,
        "valuation_basis": basis,
        "market_per_acre": market_per_acre,
        "land_per_acre": land_per_acre,
        "ag_exempt": ag_exempt,
        "ag_loss_ratio": ag_loss_ratio,
        "improved": improved,
        "acreage_variance": acreage_variance,
        "compactness": _compactness(shape_area, attrs.get("Shape__Length")),
        "owner_occupied": owner_occupied,
        "held_years": _held_years(attrs.get("deedEffDate")),
        "land": {k: attrs.get(k) for k in LAND_FIELDS},
        "improvement": {k: attrs.get(k) for k in IMPROVEMENT_FIELDS},
        "entity": {k: attrs.get(k) for k in ENTITY_FIELDS},
        "status": {k: attrs.get(k) for k in STATUS_FIELDS},
        "deed": {
            "effective_date": _epoch_ms_to_iso(attrs.get("deedEffDate")),
            "file_date": _epoch_ms_to_iso(attrs.get("deedFileDate")),
            "type_code": attrs.get("deedTypeCd"),
            "number": attrs.get("deedNum"),
        },
        "raw_attributes": attrs,
        "warnings": [],
    }


def _query(
    where: str,
    geometry: Optional[str] = None,
    out_fields: str = "*",
    return_geometry: bool = True,
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Execute ArcGIS query and return features and spatialReference."""
    params = {
        "where": where,
        "outFields": out_fields,
        "outSR": "4326",
        "returnCentroid": "true" if return_geometry else "false",
        "returnGeometry": "true" if return_geometry else "false",
        "f": "json",
    }
    
    if geometry:
        params.update({
            "geometry": geometry,
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        })
    
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{BASE_URL}/query", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise CollinCADError(f"HTTP error: {e}") from e
    except Exception as e:
        raise CollinCADError(f"Query failed: {e}") from e
    
    # ArcGIS returns 200 with error body
    if "error" in data:
        raise CollinCADError(f"ArcGIS error: {data['error']}")
    
    return data.get("features", []), data.get("spatialReference")


def get_collin_parcel_data(
    property_id: Optional[int] = None,
    parcel_id: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> dict[str, Any]:
    """Fetch parcel data from Collin CAD. Exactly one lookup method required.
    
    Returns:
        Dict with parcel data, matches (if ambiguous), and warnings.
    
    Raises:
        CollinCADError: On query failure
        ParcelNotFound: No match
        AmbiguousParcel: Multiple matches (returns first + all in matches)
    """
    # Validate input
    payload = ParcelLookupInput(
        property_id=property_id,
        parcel_id=parcel_id,
        address=address,
        city=city,
        latitude=latitude,
        longitude=longitude,
    )
    
    # Build query
    if payload.property_id:
        where = f"PROP_ID={payload.property_id}"
        features, spatial_ref = _query(where)
    elif payload.parcel_id:
        where = f"geoID='{_sql_quote(payload.parcel_id)}'"
        features, spatial_ref = _query(where)
    elif payload.latitude and payload.longitude:
        geometry = f"{payload.longitude},{payload.latitude}"
        features, spatial_ref = _query("1=1", geometry=geometry)
    elif payload.address:
        # Address query: situsBldgNum + situsStreetName (+ city if provided)
        parts = payload.address.strip().split(None, 1)
        if len(parts) < 2:
            raise CollinCADError("Address must include house number and street name")
        
        house_num, street = parts
        where_parts = [
            f"situsBldgNum='{_sql_quote(house_num)}'",
            f"UPPER(situsStreetName) LIKE '%{_sql_quote(street.upper())}%'",
        ]
        
        if payload.city:
            where_parts.append(f"UPPER(situsCity)='{_sql_quote(payload.city.upper())}'")
        
        where = " AND ".join(where_parts)
        features, spatial_ref = _query(where)
    else:
        raise CollinCADError("No lookup method provided")
    
    # Handle results
    if not features:
        return {
            "parcel": None,
            "matches": [],
            "warnings": ["No parcel found in Collin County; coverage is county-wide"],
        }
    
    # Shape all matches
    shaped = [_shape_parcel(f, spatial_ref) for f in features]
    
    # If multiple, return first + all matches + warning
    if len(shaped) > 1:
        result = shaped[0].copy()
        result["matches"] = [
            {"property_id": s["property_id"], "parcel_id": s["parcel_id"], "situs": s["situs"]}
            for s in shaped[:10]  # Cap at 10
        ]
        result["warnings"].append(
            f"Ambiguous: {len(shaped)} parcels matched; returning first by PROP_ID"
        )
        return {"parcel": result, "matches": result["matches"], "warnings": result["warnings"]}
    
    return {"parcel": shaped[0], "matches": [], "warnings": []}


def get_neighborhood_comps(
    nbhd_code: str,
    land_type_code: Optional[str] = None,
    min_acres: Optional[float] = None,
    max_acres: Optional[float] = None,
    min_cohort: int = MIN_COMP_COHORT,
) -> dict[str, Any]:
    """Median appraised value per acre across a CCAD neighborhood cohort.

    The appraisal district groups comparable parcels under `nbhdCode`, so this
    is a comp basis drawn from the same source as the subject's own valuation
    rather than from asking prices.

    Returns:
        Dict with the cohort definition, `count`, medians, and `warnings`.
        Medians are None when the cohort is smaller than `min_cohort` — a
        median over three parcels is noise dressed as a benchmark.
    """
    if not nbhd_code:
        raise CollinCADError("nbhd_code is required for a neighborhood comp query")

    where_parts = [f"nbhdCode='{_sql_quote(nbhd_code)}'", "landSizeAcres>0"]
    if land_type_code:
        where_parts.append(f"landTypeCode='{_sql_quote(land_type_code)}'")
    if min_acres is not None:
        where_parts.append(f"landSizeAcres>={min_acres}")
    if max_acres is not None:
        where_parts.append(f"landSizeAcres<={max_acres}")

    features, _ = _query(
        " AND ".join(where_parts),
        out_fields="PROP_ID,landSizeAcres,prevValMarket,prevValLand,noticeValMarket,noticeValLand,currValMarket,currValLand",
        return_geometry=False,
    )

    warnings: list[str] = []
    if len(features) >= MAX_RECORD_COUNT:
        warnings.append(
            f"Cohort hit the {MAX_RECORD_COUNT}-record service cap; medians are "
            "computed over a truncated sample"
        )

    market_per_acre: list[float] = []
    land_per_acre: list[float] = []

    for feature in features:
        attrs = feature.get("attributes", {})
        acres = attrs.get("landSizeAcres")
        if not acres or acres <= 0:
            continue

        # Same currVal -> noticeVal -> prevVal walk as the parcel path: the
        # 2027 roll is InProgress, so only prevVal is populated today.
        valuation = None
        for prefix in ("currVal", "noticeVal", "prevVal"):
            valuation = _valuation_block(attrs, prefix)
            if valuation:
                break
        if not valuation:
            continue

        market_per_acre.append(valuation["market"] / acres)
        if valuation["land"]:
            land_per_acre.append(valuation["land"] / acres)

    count = len(market_per_acre)
    if count < min_cohort:
        warnings.append(
            f"Only {count} comparable parcels in neighborhood {nbhd_code} "
            f"(minimum {min_cohort}); medians withheld"
        )
        return {
            "nbhd_code": nbhd_code,
            "land_type_code": land_type_code,
            "count": count,
            "median_market_per_acre": None,
            "median_land_per_acre": None,
            "warnings": warnings,
        }

    return {
        "nbhd_code": nbhd_code,
        "land_type_code": land_type_code,
        "count": count,
        "median_market_per_acre": statistics.median(market_per_acre),
        "median_land_per_acre": statistics.median(land_per_acre) if land_per_acre else None,
        "warnings": warnings,
    }


def run_parcel_lookup(**kwargs: Any) -> str:
    """Agent/MCP wrapper: never raises, returns JSON."""
    try:
        result = get_collin_parcel_data(**kwargs)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def run_neighborhood_comps(**kwargs: Any) -> str:
    """Agent/MCP wrapper: never raises, returns JSON."""
    try:
        result = get_neighborhood_comps(**kwargs)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# CLI
app = typer.Typer(help="Collin CAD parcel lookup CLI")


@app.command()
def lookup(
    prop_id: Optional[int] = typer.Option(None, "--prop-id", help="PROP_ID"),
    geo_id: Optional[str] = typer.Option(None, "--geo-id", help="geoID (parcel ID)"),
    address: Optional[str] = typer.Option(None, "--address", help="Situs address"),
    city: Optional[str] = typer.Option(None, "--city", help="Situs city (with --address)"),
    lat: Optional[float] = typer.Option(None, "--lat", help="Latitude"),
    lng: Optional[float] = typer.Option(None, "--lng", help="Longitude"),
):
    """Look up parcel by property ID, parcel ID, address, or lat/lon."""
    try:
        result = get_collin_parcel_data(
            property_id=prop_id,
            parcel_id=geo_id,
            address=address,
            city=city,
            latitude=lat,
            longitude=lng,
        )
        typer.echo(json.dumps(result, indent=2, default=str))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def comps(
    nbhd: str = typer.Option(..., "--nbhd", help="nbhdCode, e.g. SMCR"),
    land_type: Optional[str] = typer.Option(None, "--land-type", help="landTypeCode, e.g. D1IP"),
    min_acres: Optional[float] = typer.Option(None, "--min-acres", help="Lower acreage bound"),
    max_acres: Optional[float] = typer.Option(None, "--max-acres", help="Upper acreage bound"),
):
    """Median appraised value per acre across a CCAD neighborhood cohort."""
    try:
        result = get_neighborhood_comps(
            nbhd_code=nbhd,
            land_type_code=land_type,
            min_acres=min_acres,
            max_acres=max_acres,
        )
        typer.echo(json.dumps(result, indent=2, default=str))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app()
