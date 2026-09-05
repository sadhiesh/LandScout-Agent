# Enricher Agent

Port 8003. Adds the facts that determine buy quality to each candidate parcel.

**Owns:** the enricher registry in `tools/enrichment/` — currently `landwatch_detail` and `county_comps`.

**Does not own:** search, scoring, or report generation.

## Contract

- Receives from Supervisor: `{parcels, criteria}`.
- Returns to Supervisor: the same parcels with an `enrichment` dict merged on, plus `sources_used` naming every enricher that ran and every one that failed.

## Rules

- Enrichers are pluggable and independent. A failing enricher is logged and skipped — it never fails the whole run. Record it in `sources_used` so a missing field is visibly missing rather than silently absent.
- Only enabled enrichers run. `fema_flood`, `usda_soil`, and `zoning` are registered but disabled stubs; do not enable them without a decision recorded in `docs/decisions/`.
- Never invent an enrichment value. An unavailable fact is `None` with a note, not an estimate.
- Enrichment is per-parcel and cacheable in `memory/`. Do not re-fetch a fact already persisted for the same parcel within the run.

## Failure behavior

- Adapter auth or rate-limit failure: retry once, then degrade with a note in `sources_used`. See `tools/enrichment/CLAUDE.md` for per-source limits.
