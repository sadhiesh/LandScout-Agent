# Grayson CAD tool brief (placeholder)

Placeholder for future Grayson County CAD implementation. Read before implementing Grayson CAD.

## Source of truth

**Service**: `https://maps.co.grayson.tx.us/arcgis/rest/services/Grayson/Grayson_County_Public_Interactive_Map/MapServer/5` (Parcels layer)

Public map server (not FeatureServer like Collin). **Geometry-only coverage**: the layer exposes `PROP_ID`, `GEO_ID`, `LONG_GEO_I`, shape fields (area, length, geometry), and edit metadata only. **No owner, no situs address, no valuation, no appraised acreage.**

**Coverage**: Grayson County parcels, 2000 maxRecordCount, SR 102738 (2276), supports advanced queries and datum transformation.

## Critical differences from Collin CAD

1. **Geometry-only schema.** Unlike Collin's 100+ attribute fields, Grayson exposes:
   - `PROP_ID` (Integer): property ID
   - `GEO_ID` (String, 50): parcel ID
   - `LONG_GEO_I` (String, 50): long geo ID
   - `Shape` (Geometry): polygon
   - `Shape.STLength()`, `Shape.STArea()`: computed shape metrics
   - Edit metadata: `last_edi_1`, `last_edite`, `created_da`, `created_us`
   
   **No**: owner, situs, valuation, land/improvement, deed, city entity code.

2. **Centroid must be computed.** `Supports Returning Geometry Centroid: false` per the layer metadata. The client must compute the centroid from polygon rings if needed.

3. **MapServer, not FeatureServer.** Query endpoint is `/MapServer/5/query`, not `/FeatureServer/4/query`. Capabilities differ slightly (e.g., no `returnCentroid` parameter).

## Future implementation

When building `grayson_cad/grayson_cad.py`:

- Output shape: `{"parcel_id": GEO_ID, "property_id": PROP_ID, "geometry": ..., "centroid": {...}, "gis_acres": ...}` plus an explicit `{"capabilities": "geometry_only"}` flag so the scorer knows valuation/owner/situs are unavailable.
- Centroid: compute from polygon rings (average x/y of all ring points).
- GIS acres: `Shape.STArea()` in the response is square feet; divide by 43560.
- Same error contract: ArcGIS returns HTTP 200 with `{"error": ...}` body on malformed queries.
- `outSR=4326` is still required (native SR 102738 is state-plane feet).

## Conventions

Follow Collin CAD conventions: `extra="forbid"` on input model, JSON errors from agent wrapper, offline tests against fixtures, `scripts/capture_fixtures.py` as the only live caller, Typer CLI. Single-file implementation per the tool layout.

## Absolute prohibitions

- Do **not** call the live service from tests.
- Do **not** fabricate owner, valuation, or situs fields absent from the layer — missing is explicit.
- Do **not** skip the centroid computation; `returnCentroid` is unsupported.
- Do **not** assume the Collin CITY_CODES map applies; Grayson has different jurisdiction codes (not yet known).

## Status

**Not implemented.** This is a placeholder brief so the future build is informed.
