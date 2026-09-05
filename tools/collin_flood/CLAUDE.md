# Collin County flood tool brief

Read this before editing anything under `tools/collin_flood/`. Shared tool conventions are in `tools/CLAUDE.md`; project-level rules are in the repo-root `CLAUDE.md`.

## Layout

- `collin_flood/collin_flood.py` — single ~300-line module: constants, geometry helpers (duplicated from fema_flood), lookup logic, agent wrapper, CLI.
- `collin_flood/__init__.py` — exports public API.
- `scripts/capture_fixtures.py` — the only code permitted to hit the live service.
- `tests/fixtures/` — offline JSON responses for pytest.
- `tests/test_collin_flood.py` — offline tests against fixtures.

## Entry points

- Library: `from collin_flood import get_collin_floodplain_from_geometry`. Call `get_collin_floodplain_from_geometry(geometry, wkid=None, parcel_acres=None) -> dict`.
- Agent wrapper: `collin_flood.run_collin_floodplain_check(**kwargs) -> str` (returns JSON string, never raises into agent loop).
- CLI: `python -m collin_flood.collin_flood check --geometry <json> [--wkid <int>] [--acres <float>]` for manual checks and fixture capture.

## Source of truth

**Service**: `https://services9.arcgis.com/8qadn7hfDj86yxAd/arcgis/rest/services/Collin_County_Flood__Bo4_/FeatureServer/0` (updated 2026-09-01: service moved to new host/path)

Collin County-specific floodplain layer. Official Collin County service. Public, no authentication required. ArcGIS item ID: `1b0d1e2297834da08947fccd19dc6fab`.

**Coverage**: Collin County only.

**Layer 0 fields**: `FLD_AR_ID`, `FLD_ZONE`, `FLOODWAY`, `SFHA_TF`, `STATIC_BFE`, `V_DATUM`, `DEPTH`, `LEN_UNIT`, `VELOCITY`, `VEL_UNIT`, `AR_REVERT`, `BFE_REVERT`, `DEP_REVERT`, `SOURCE_CIT`, `HYDRO_ID`, `CST_MDL_ID`, `LEVEE_STAT`, `PAL_DATE`.

**Key differences from FEMA NFHL**:
- **No FIRM panel field** — the Bo4 layer does not carry `FIRM_PAN` or `FIRM_PANEL_ID`. Output returns `firm_panel: null` with a note.
- **`FLOODWAY` is a direct field** (`Y`/`N` string), not a `ZONE_SUBTY` value.
- **Field names differ slightly**: same semantic coverage as FEMA but field naming is Collin-specific.

**Native SR**: Same as Collin CAD — 2276 (NAD83 Texas North Central ftUS). Server-side reprojection via `inSR` and `outSR`.

## Critical correctness traps

### 1. Sentinel value -9999 means "no data"

**`STATIC_BFE`, `DEPTH`, `VELOCITY`, `BFE_REVERT`, `DEP_REVERT` use `-9999` as a "no value" sentinel.** Must normalize to `null` in output.

**Rule**: `_clean(value)` helper checks for `-9999` and converts to `None`.

### 2. ArcGIS returns HTTP 200 with error bodies

**ArcGIS FeatureServer returns HTTP 200 with an `{"error": {...}}` body** on bad queries. The client must check for `"error"` in the JSON and raise `CollinFloodError`.

### 3. spatialReference is not on the geometry object

**Feature geometries carry no `spatialReference` key.** It lives at the response top level. The Collin CAD tool was fixed to attach the SR onto returned geometry so `_resolve_wkid` can read it.

**Rule**: `_resolve_wkid(geometry, wkid)` checks `geometry.get("spatialReference")` first, then falls back to the explicit `wkid` parameter.

### 4. A parcel intersects many floodplain polygons

**A single parcel can intersect 8+ floodplain zones** (observed on test parcel). Output includes `details.flood_zone` (highest risk), `details.all_zones` (unique list), and `details.raw` (every feature with its area fraction).

### 5. No FIRM panel field

**The Bo4 layer has no FIRM panel field.** Output includes `firm_panel: null` with a note rather than omitting the key or attempting to derive it from FEMA.

## Affected acreage via area ratio

Same rationale as FEMA flood tool:

- `affected_fraction = sum(shapely.intersection.area) / shapely.parcel.area`
- `affected_acres = affected_fraction * parcel_acres` (from CAD tool's `landSizeAcres`/`gis_acres`)
- Ratio is CRS-invariant; works in 2276 ftUS, 4326 degrees, or any projected plane.

## Server-side reprojection via inSR/outSR

Same as FEMA flood tool:

1. Parse `wkid` from geometry or accept explicit parameter.
2. Send polygon with `inSR=<wkid>`.
3. Request `outSR=<wkid>`.
4. Parcel and flood geometry land in the same plane; shapely computes intersections directly.

**No `pyproj` dependency.**

## Vocabulary SSOT

`COLLIN_FLOOD_URL`, `NO_DATA_SENTINEL = -9999`, and flood zone risk tiers are declared at the top of `collin_flood.py`. Nothing restates these.

## Conventions

- Geometry input: dict with `rings` and optionally `spatialReference: {"wkid": int}`.
- `wkid` parameter: optional override if geometry lacks embedded SR.
- `parcel_acres` parameter: optional; if provided, enables `affected_acres` output.
- Library callers get typed exceptions (`CollinFloodError`). Agent/MCP boundary returns JSON `{"error": "..."}`, never raises into agent loop.
- Output structure:
  ```python
  {
      "floodplain": bool,
      "details": {
          "flood_zone": str | None,
          "all_zones": [str, ...],
          "sfha": bool,
          "floodway": bool,
          "bfe": float | None,
          "firm_panel": None,  # Bo4 layer has no FIRM panel field
          "coverage": {
              "affected_fraction": float,
              "affected_acres": float | None
          },
          "raw": [
              {
                  "zone": str,
                  "floodway": bool,
                  "sfha": bool,
                  "bfe": float | None,
                  "affected_fraction": float,
                  "affected_acres": float | None
              },
              ...
          ]
      }
  }
  ```
- Tests stay **offline** against fixtures in `tests/fixtures/`. Recapture via `scripts/capture_fixtures.py` if needed.

## Absolute prohibitions

- Do **not** call the live service from tests (ADR 0003).
- Do **not** treat `-9999` as a real BFE/depth/velocity value.
- Do **not** check only HTTP status code for errors — ArcGIS returns 200 with error bodies.
- Do **not** hardcode a WKID or assume the parcel is in a specific CRS.
- Do **not** add `pyproj` or attempt client-side reprojection — use `inSR`/`outSR`.
- Do **not** attempt to populate `firm_panel` from FEMA or another source — return `null` with a note.
- Do **not** add dependencies beyond `httpx`, `pydantic`, `shapely`, `typer` (all in `pyproject.toml` after TODO 10).

## Decision log (tool)

| Date (YYYY-MM-DD) | Change / Decision | Rationale | Files Touched |
| --- | --- | --- | --- |
| 2026-08-29 | Separate `tools/collin_flood/` package over merging into `fema_flood` | Collin's Bo4 layer has different fields (`FLOODWAY` direct field, no FIRM panel) and different source authority. Separate tools keep each simple. | `CLAUDE.md`, `collin_flood.py` |
| 2026-08-29 | Duplicate geometry helpers rather than extracting to shared package | Two tools do not justify a `tools/flood_common/`. Extract only when a third flood source is added. | `CLAUDE.md`, `collin_flood.py`, `../fema_flood/fema_flood.py` |
| 2026-08-29 | Return `firm_panel: null` with a note, not omit the key | Bo4 has no FIRM panel field. Returning `null` makes the absence explicit; omitting the key invites confusion about whether it was checked. | `CLAUDE.md`, `collin_flood.py` |
