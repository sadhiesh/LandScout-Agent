# Enrichment tools

Each file here is one data source: one function, typed in and out, following the shared error contract in `tools/CLAUDE.md`. They are discovered through a registry so the Enricher agent never hardcodes a source list.

**Nothing in this folder is implemented yet.** This brief is the contract to build against.

## Registry

```python
class Enricher(Protocol):
    name: str
    enabled: bool
    def enrich(self, parcel: Parcel) -> dict: ...   # facts merged onto parcel.enrichment

REGISTRY: list[Enricher] = []   # populate with @register
```

A failing enricher is logged and skipped. It is **never** fatal to the run — one dead source must not cost the user their shortlist. Every run reports `sources_used` naming what ran and what failed, so a missing field reads as missing rather than absent.

## Sources

| File | Auth | Notes |
| --- | --- | --- |
| `landwatch_detail.py` | none | Wraps `get_detail` from `tools/landwatch/`. Price history, days on market, description features, utilities/access keywords. Enabled. |
| `county_comps.py` | none | Parcel price-per-acre against the county median, derived from a broader LandWatch search. Registered but **disabled** (not fully setup). Costs extra searches — respect the 1 req/s client throttle. |
| `flood_fema.py` | none | FEMA NFHL flood zone lookup. Enabled. |
| `soil_usda.py` | none | Registered but **disabled** stub. |
| `zoning.py` | key TBD | Registered but **disabled** stub. |

Do not enable a stub without recording an ADR in `docs/decisions/` — the disabled set is a deliberate scope decision, not an oversight.

## Rules

- Keys come from the environment, declared as placeholders in `config/.env.example`. Never inline a key, and never commit a real `.env`.
- Base URLs and rate limits belong in `config/data_sources.yaml`, not scattered through adapters.
- If two sources share a transport pattern, extract one shared helper. Do not write a second client for the same protocol.
- An unavailable fact is `None` with a note in `sources_used`. Never estimate, interpolate, or fall back to a plausible-looking default — a fabricated fact flows straight into a score and then into a rationale a human will trust.
- Capture one real response per source as a fixture under `tests/fixtures/` and test against it. Live calls from tests burn quota and break when a site changes mid-session.
