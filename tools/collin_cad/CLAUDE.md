# Collin CAD tool brief

Read this before editing anything under `tools/collin_cad/`. Shared tool conventions are in `tools/CLAUDE.md`; project-level rules are in the repo-root `CLAUDE.md`.

## Layout

- `collin_cad/collin_cad.py` — single ~400-line module: constants, client, models, lookup logic, agent wrapper, CLI.
- `collin_cad/__init__.py` — exports public API.
- `scripts/capture_fixtures.py` — the only code permitted to hit the live service.
- `tests/fixtures/` — offline JSON responses for pytest.
- `tests/test_collin_cad.py` — offline tests against fixtures.

## Entry points

- Library: `from collin_cad import get_collin_parcel_data, get_neighborhood_comps, ParcelLookupInput`. Call `get_collin_parcel_data(property_id=...) -> dict`.
- Agent wrappers: `run_parcel_lookup(**kwargs) -> str` and `run_neighborhood_comps(**kwargs) -> str` (JSON strings, never raise into an agent loop).
- CLI: `python -m collin_cad.collin_cad lookup --prop-id / --geo-id / --address / --lat --lng`, and `... comps --nbhd SMCR [--land-type D1IP]` for manual checks and fixture capture.

## Source of truth

**Service**: `https://services2.arcgis.com/uXyoacYrZTPTKD3R/arcgis/rest/services/CCAD_Parcel_Feature_Set/FeatureServer/4`

Official Collin Central Appraisal District service, copyright `Collin Central Appraisal District`. **Layer 4 (Parcels) only** — sibling layers (City Limits, School Districts, Special Districts, Subdivisions, Abstracts) are not queried per user decision. **No `attachments` key** in the output — no layer in the service exposes attachments.

**Coverage**: 439,668 parcels, all of Collin County. `Query,Extract`, `maxRecordCount: 2000`, `Use Standardized Queries: True`.

**Native SR**: 2276 (NAD83 Texas North Central ftUS). **`outSR=4326` is required** or geometry comes back in state-plane feet. `returnCentroid=true` is supported and returns the centroid in `outSR`.

## Critical correctness traps

### 1. situsCity is NOT jurisdiction

**`situsCity` is a mailing city and does NOT match the taxing jurisdiction.** 52,842 of 439,668 parcels (12%) have a `situsCity` but a null `entityCityCode` — a city mailing address on unincorporated county land. Conversely `entityCityCode='CAN'` (Anna) parcels have `situsCity` values of ALLEN, BLUE RIDGE, CELINA, MCKINNEY, and MELISSA.

**Rule**: `city` derives from `entityCityCode` alone via `CITY_CODES`, falling back to `"Unincorporated (Collin County)"` when null. `situsCity` is reported inside `situs` but never promoted to `city`. For land investment the jurisdiction determines zoning authority and annexation exposure — a wrong city is worse than an explicit Unincorporated.

### 2. All current-year values are null

**`propYear=2027` and `propStatus=InProgress` on every row.** `currValMarket IS NOT NULL` → 0 rows, `noticeValMarket IS NOT NULL` → 0 rows. Only `prevValMarket` (2026) is populated, on 429,514 rows.

**Rule**: The valuation block walks `currVal` → `noticeVal` → `prevVal` and returns the first with non-null `Market`, reporting `year` and `basis` so consumers know they are reading a prior-year value. Reading `currVal*` directly would value every parcel in Collin County at zero.

### 3. ArcGIS returns HTTP 200 with error bodies

**ArcGIS FeatureServer returns HTTP 200 with an `{"error": {...}}` body** on bad where clauses and malformed geometry. Status-code-only error handling will silently treat these as empty results. The client must check for `"error"` in the JSON and raise `CollinCADError`.

## Field names and quirks

**A wrong name in a field-group tuple does not raise — it yields a block of nulls.** Five of the original tuples named attributes the service never returns (`mailingAddress1`, `legalDescr`, `landValMarket`, `deedHeirCode`, `situsZipCode`), so `owner`, `legal`, and `deed` came back empty for months without a single error. Verify any new name against a live `outFields=*` response before adding it.

- Situs house-number field is **`situsBldgNum`**, not `situsNumber`. Zip is **`situsZip`**, not `situsZipCode`.
- Owner mailing fields are `ownerAddrLine1/2`, `ownerAddrCity/State/Zip` — there is no `mailing*` prefix on this layer.
- Legal description is **`legalDescription`**; deed fields are `deedTypeCd` and `deedNum` (no `deedHeirCode` or `deedBuyerName`).
- There is no `{prefix}Ag` valuation field. The ag figure is `{prefix}AgLoss`.
- Address queries need `UPPER()` wrapping: `UPPER(situsStreetName) LIKE '%...%'` and `UPPER(situsCity) = '...'`.
- `PROP_ID` accepts both `PROP_ID=983555` and `PROP_ID='983555'`.
- `geoID` is the parcel ID field (e.g. `R-6782-000-0140-1`).
- Point queries: `geometry=<lng>,<lat>&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects`.

## Vocabulary SSOT

`CITY_CODES` (30-entry map), attribute-group tuples (`SITUS_FIELDS`, `OWNER_FIELDS`, `LEGAL_FIELDS`, `LAND_FIELDS`, `IMPROVEMENT_FIELDS`, `DEED_FIELDS`, `ENTITY_FIELDS`), and the three valuation prefixes (`currVal`, `noticeVal`, `prevVal`) are declared at the top of `collin_cad.py`. Nothing restates these lists.

**entityCityCode domain** (30 values, all verified present in the data): `CAL` Allen, `CAN` Anna, `CBL` Blue Ridge, `CCR` Carrollton, `CCL` Celina, `CDA` Dallas, `CFV` Fairview, `CFC` Farmersville, `CFR` Frisco, `CGA` Garland, `CJO` Josephine, `CLA` Lavon, `CLC` Lowry Crossing, `CLU` Lucas, `CMC` McKinney, `CML` Melissa, `CMR` Murphy, `CNV` Nevada, `CNH` New Hope, `CPK` Parker, `CPL` Plano, `CPN` Princeton, `CPR` Prosper, `CRC` Richardson, `CRY` Royse City, `CSA` Sachse, `CSP` St. Paul, `CVA` Van Alstyne, `CWS` Weston, `CWY` Wylie. 61,709 parcels have no city entity (unincorporated).

## Conventions

- `ParcelLookupInput(BaseModel)` with `model_config = ConfigDict(extra="forbid")` and exactly-one-of validation across `property_id`, `parcel_id`, `address` fields, and `latitude`+`longitude`.
- Library callers get typed exceptions (`CollinCADError`, `ParcelNotFound`, `AmbiguousParcel`). Agent/MCP boundary returns JSON `{"error": "..."}`, never raises into agent loop.
- String literals pass through `_sql_quote()`, which doubles embedded single quotes for ArcGIS where-clause literals. `httpx` does the URL encoding.
- Address lookups are frequently ambiguous and must handle multi-match: `situsBldgNum='1200' AND UPPER(situsCity)='PLANO'` returns 78 rows. `matches` is capped at 10 summaries so an over-broad address does not return a large payload. First match by `PROP_ID` (deterministic) goes in `parcel`, every candidate in `matches`, and a warning.
- Empty result → `parcel: null` plus a `warnings` entry explaining the Collin County coverage limit.
- Derived fields the scorer needs: `market_per_acre`, `land_per_acre`, `ag_exempt` (from `landAgAcres` and ag-loss figure), `ag_loss_ratio` (share of market value the ag valuation hides — carrying-cost saving today, rollback exposure on change of use), `improved` (from `imprvMainArea` / `imprvYearBuilt`), `gis_acres` (from `Shape__Area`), `acreage_variance` (GIS against appraised `landSizeAcres`), `compactness` (Polsby-Popper from `Shape__Area` and `Shape__Length` — acreage says nothing about shape), `owner_occupied` (owner mailing line against the rebuilt situs street line), and `held_years` (from `deedEffDate`, resolved here so scoring stays a pure function).
- `entity` and `status` blocks carry the fields the tax-burden, land-use, and developability dimensions read: `entityCodes`, `entitySchoolCode`, `entityMUD`, `entityTIF`, `entitySBCL`, and `nbhdCode`, `propSubType`, `propCategoryCode`, `exemptCodes`, `exemptHmstdFlag`, `protestCode`, `udiPropFlag`, `propSplitFromPID`.
- `get_neighborhood_comps(nbhd_code, land_type_code=...)` returns the median appraised value per acre across a `nbhdCode` cohort, using the same `currVal` → `noticeVal` → `prevVal` walk. Medians are withheld below `MIN_COMP_COHORT` parcels, and a cohort of exactly `MAX_RECORD_COUNT` (2000) is flagged as truncated.
- Epoch-millisecond date fields (`deedEffDate`, `deedFileDate`, `propCreateDate`, `noticeDate`) convert to ISO dates.
- `raw_attributes` keeps the untouched ArcGIS attribute bag so the shaping step cannot lose anything.
- Tests stay **offline** against fixtures in `tests/fixtures/`. If the live service changes, recapture fixtures via `scripts/capture_fixtures.py`.

## Absolute prohibitions

- Do **not** call the live service from tests (ADR 0003).
- Do **not** fall back to `situsCity` when deriving `city` — 12% of the county would be wrong.
- Do **not** read `currVal*` directly for valuation — every parcel would value at zero.
- Do **not** check only HTTP status code for errors — ArcGIS returns 200 with error bodies.
- Do **not** add dependencies beyond `httpx`, `pydantic`, `typer` (all already in `pyproject.toml`).
- Do **not** query sibling layers — user scoped the tool to the parcel layer only.

## Decision log (tool)

| Date (YYYY-MM-DD) | Change / Decision | Rationale | Files Touched |
| --- | --- | --- | --- |
| 2026-08-29 | Official CCAD service (services2.arcgis.com, layer 4) over the Celina mirror | Celina mirror covers only 39,505 parcels (9% of county) despite the county-wide name. Official service is 439,668 parcels. | `CLAUDE.md`, `collin_cad.py` |
| 2026-08-29 | City from `entityCityCode` only; never fall back to `situsCity` | 52,842 parcels have `situsCity` but null `entityCityCode` (mailing address on unincorporated land). Wrong jurisdiction is worse than explicit Unincorporated. | `CLAUDE.md`, `collin_cad.py` |
| 2026-08-29 | Valuation fallback `currVal` → `noticeVal` → `prevVal`, reporting year and basis | Service-wide `propStatus=InProgress` for 2027 roll; `currValMarket IS NOT NULL` returns 0 rows. Reading `currVal*` directly zeros every parcel. | `CLAUDE.md`, `collin_cad.py` |
| 2026-08-29 | Parcel layer 4 only; omit `attachments` key rather than empty array | No layer has `hasAttachments: true`. User chose parcel-only scope for simplicity. Empty key invites future readers to populate it. | `CLAUDE.md`, `collin_cad.py` |
| 2026-08-29 | Single-file core module `collin_cad.py` over 5 separate modules | User request for consolidation. All constants, client, models, logic, agent wrapper, CLI in one ~400-line file for readability. | `CLAUDE.md`, `collin_cad.py` |
