# FEMA NFHL tool brief

Read this before editing anything under `tools/fema_flood/`. Shared tool conventions are in `tools/CLAUDE.md`; project-level rules are in the repo-root `CLAUDE.md`.

## Layout

- `fema_flood/fema_flood.py` — single ~350-line module: constants, geometry helpers, lookup logic, agent wrapper, CLI.
- `fema_flood/__init__.py` — exports public API.
- `scripts/capture_fixtures.py` — the only code permitted to hit the live service.
- `tests/fixtures/` — offline JSON responses for pytest.
- `tests/test_fema_flood.py` — offline tests against fixtures.

## Entry points

- Library: `from fema_flood import get_fema_flood_from_geometry`. Call `get_fema_flood_from_geometry(geometry, wkid=None, parcel_acres=None) -> dict`.
- Agent wrapper: `fema_flood.run_fema_flood_check(**kwargs) -> str` (returns JSON string, never raises into agent loop).
- CLI: `python -m fema_flood.fema_flood check --geometry <json> [--wkid <int>] [--acres <float>]` for manual checks and fixture capture.

## Source of truth

**Service**: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer` (updated 2026-09-01: moved from `/gis/nfhl/rest` to `/arcgis/rest`)

FEMA National Flood Hazard Layer (NFHL) ArcGIS MapServer. Public, no authentication required.

**Coverage**: Continental US. `Query,Extract`, rate limit unspecified (light use assumed).

**Layers used**:
- **Layer 28: Flood Hazard Zones** (`FLD_AR_ID`, `FLD_ZONE`, `ZONE_SUBTY`, `SFHA_TF`, `STATIC_BFE`, `V_DATUM`, `DEPTH`, `LEN_UNIT`, `VELOCITY`, `VEL_UNIT`, `AR_REVERT`, `BFE_REVERT`, `DEP_REVERT`, `SOURCE_CIT`)
  - **Floodway detection**: `ZONE_SUBTY = 'FLOODWAY'` (not a separate layer).
  - **Layer 27 is Flood Hazard *Boundaries* (polyline), not floodways.**
- **Layer 3: FIRM Panels** (`FIRM_PAN`, `EFF_DATE`, `PANEL_NO`, `SOURCE_CIT`)
- **Layer 1: LOMRs** (polygon, `CASE_NO`, `EFF_DATE`, `STATUS`)
- **Layer 34: LOMAs** (point, `CASENUMBER`, `DETERMINATIONTYPE`, `OUTCOME`)
  - **Layer 9 is Coastal Gages, not LOMAs/LOMRs.**

**Native SR**: Varies by feature. Geometries carry no embedded SR; response has top-level `spatialReference`. Server-side reprojection via `inSR` and `outSR`.

## Critical correctness traps

### 1. Sentinel value -9999 means "no data"

**`STATIC_BFE`, `DEPTH`, `VELOCITY`, `BFE_REVERT`, `DEP_REVERT` use `-9999` as a "no value" sentinel.** Must normalize to `null` in output. A parcel with `STATIC_BFE: -9999` does **not** have a base flood elevation of negative 9999 feet.

**Rule**: `_clean(value)` helper checks for `-9999` and converts to `None` before returning any BFE/depth/velocity field.

### 2. ArcGIS returns HTTP 200 with error bodies

**ArcGIS MapServer returns HTTP 200 with an `{"error": {...}}` body** on bad queries and malformed geometry. Status-code-only error handling will silently treat these as empty results. The client must check for `"error"` in the JSON and raise `FEMAFloodError`.

### 3. spatialReference is not on the geometry object

**Feature geometries carry no `spatialReference` key.** It lives at the response top level as `{"spatialReference": {"wkid": ..., "latestWkid": ...}}`. The Collin CAD tool was fixed to attach the SR onto returned geometry so `_resolve_wkid` can read it.

**Rule**: `_resolve_wkid(geometry, wkid)` checks `geometry.get("spatialReference")` first, then falls back to the explicit `wkid` parameter. Caller must supply one or the other.

### 4. A parcel intersects many flood polygons

**A single parcel can intersect 10+ flood zones** (observed: 11 NFHL zones, 8 Collin zones on test parcel). Returning a single scalar `flood_zone` would be a lie.

**Rule**: Output has `details.worst_zone` (highest risk by zone priority), `details.all_zones` (unique list), and `details.raw` (every intersecting feature with its area fraction). The agent gets full information to reason about mixed-zone parcels.

## Affected acreage via area ratio (no hardcoded units)

**Overlap is computed as an area ratio**, which is exact under affine distortion and valid in any projected CRS — no hardcoded unit assumptions.

**Formula**: 
- `affected_fraction = sum(shapely.intersection.area) / shapely.parcel.area`
- `affected_acres = affected_fraction * parcel_acres` (where `parcel_acres` comes from the CAD tool's `landSizeAcres`/`gis_acres`)

**When acreage is not supplied**: `affected_fraction` is still reported; `affected_acres` is `null` rather than estimated from GIS geometry (which may differ from appraised acreage).

**Why ratios**: Whether the parcel arrives in EPSG:2276 (ftUS), 4326 (degrees), or another CRS, the area ratio is invariant. No `pyproj` dependency needed.

## Server-side reprojection via inSR/outSR

**`pyproj` is not installed.** Reprojection is handled by the ArcGIS service itself:

1. Parse `wkid` from the input geometry's `spatialReference` or accept explicit `wkid` parameter.
2. Send polygon rings with `inSR=<wkid>` (tells the service what CRS the input is in).
3. Request `outSR=<wkid>` (gets flood polygons back in the same CRS as the parcel).
4. Both parcel and flood geometry land in the same plane; shapely can compute intersections directly.

**Rule**: Never hardcode a WKID. Accept what the CAD tool provides (typically 2276 for Collin CAD) and pass it through.

## Vocabulary SSOT

`NFHL_BASE`, `NFHL_LAYERS` dict (layer number → name/purpose), `NO_DATA_SENTINEL = -9999`, and the flood zone risk tiers (`AE`, `AH`, `AO`, `A`, `VE`, `V`, `X` shaded, `X` unshaded) are declared at the top of `fema_flood.py`. Nothing restates these lists.

## Conventions

- Geometry input: dict with `rings` (array of coordinate rings, each ring is `[[x1,y1], [x2,y2], ...]`) and optionally `spatialReference: {"wkid": int}`.
- `wkid` parameter: optional override if geometry lacks embedded SR.
- `parcel_acres` parameter: optional; if provided, enables `affected_acres` output.
- Library callers get typed exceptions (`FEMAFloodError`). Agent/MCP boundary returns JSON `{"error": "..."}`, never raises into agent loop.
- Output structure:
  ```python
  {
      "in_flood_zone": bool,
      "details": {
          "worst_zone": str | None,
          "all_zones": [str, ...],
          "sfha": bool,
          "floodway": bool,
          "static_bfe": float | None,
          "firm_panel": str | None,
          "lomrs": [{"case_no": str, "eff_date": str, "status": str}, ...],
          "lomas": [{"case_number": str, "determination_type": str, "outcome": str}, ...],
          "coverage": {
              "affected_fraction": float,
              "affected_acres": float | None
          },
          "raw": [
              {
                  "layer": str,
                  "zone": str,
                  "zone_subtype": str | None,
                  "sfha": bool,
                  "bfe": float | None,
                  "affected_fraction": float,
                  "affected_acres": float | None
              },
              ...
          ]
      },
      "investment_impact": {
          "risk_tier": str,  # "high", "moderate", "low", "none"
          "usable_acres_discount": float,  # from criteria.yaml
          "explanation": str
      }
  }
  ```
- Tests stay **offline** against fixtures in `tests/fixtures/`. If the live service changes, recapture fixtures via `scripts/capture_fixtures.py`.

## Absolute prohibitions

- Do **not** call the live service from tests (ADR 0003).
- Do **not** treat `-9999` as a real BFE/depth/velocity value.
- Do **not** check only HTTP status code for errors — ArcGIS returns 200 with error bodies.
- Do **not** hardcode a WKID or assume the parcel is in a specific CRS.
- Do **not** add `pyproj` or attempt client-side reprojection — use `inSR`/`outSR`.
- Do **not** add dependencies beyond `httpx`, `pydantic`, `shapely`, `typer` (all in `pyproject.toml` after TODO 10).

## Decision log (tool)

| Date (YYYY-MM-DD) | Change / Decision | Rationale | Files Touched |
| --- | --- | --- | --- |
| 2026-08-29 | Server-side reprojection via `inSR`/`outSR` over `pyproj` | `pyproj` not installed; ArcGIS can reproject internally. Keeps dependencies minimal and avoids CRS catalog bloat. | `CLAUDE.md`, `fema_flood.py` |
| 2026-08-29 | Affected acreage via area ratio, not absolute area | Area ratio is CRS-invariant; works in 2276 ftUS, 4326 degrees, or any projected plane without unit assumptions. | `CLAUDE.md`, `fema_flood.py` |
| 2026-08-29 | Duplicate geometry helpers in `fema_flood` and `collin_flood` | Two tools do not justify a shared package yet. Extract to `tools/flood_common/` only when a third flood source is added. | `CLAUDE.md`, `fema_flood.py`, `../collin_flood/collin_flood.py` |
| 2026-08-29 | Return `worst_zone` + `all_zones` + full `raw`, not a single scalar | A parcel can intersect 10+ zones. Reducing to a single field loses critical information for investment decisions. | `CLAUDE.md`, `fema_flood.py` |
| 2026-08-29 | `-9999` sentinel normalized to `null` for BFE/depth/velocity | NFHL uses `-9999` to mean "no data", not a real elevation. Returning it raw would break every consumer. | `CLAUDE.md`, `fema_flood.py` |
