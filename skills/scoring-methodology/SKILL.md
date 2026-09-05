---
name: scoring-methodology
description: Weighted scoring rubric for ranking land parcels against stated investment criteria — load when computing, explaining, or debugging a parcel score.
---

# Scoring methodology

Score is a weighted sum of normalized sub-scores. Weights live in `config/criteria.yaml`; never hardcode one here or in a prompt.

## Dimensions

- **Value against comps** — price per acre versus the county median. Lower is better, normalized against the comps range rather than an absolute threshold.
- **Acreage fit** — distance from the buyer's stated acreage band. Inside the band scores full; outside decays rather than dropping to zero.
- **Criteria match** — how many stated structured filters the parcel actually satisfies.
- **Water and terrain** — waterfront, geography, and terrain flags the buyer asked for.
- **Access and utilities** — road access, power, water availability, drawn from description keywords and detail fields.
- **Market signal** — days on market and price reductions. A long-listed parcel with cuts is negotiating leverage, not automatically a defect.

## Normalization rules

Each dimension normalizes to 0–1 before weighting, so no dimension dominates through unit scale. A missing enrichment field is **not** scored as zero — renormalize across the dimensions that have data and record which were skipped. Scoring an absent fact as "bad" punishes a parcel for a dead API.

## Writing the rationale

Generate the qualitative rationale from the actual breakdown and enrichment fields for that specific parcel, never from a template.

Cite the concrete driver: "$4,100/acre against a county median of $6,800, and on market 190 days with two price cuts" — not "strong value and motivated seller." If a claim cannot be traced to a number in the breakdown, it does not go in the rationale. When the data is thin, say the data is thin; a hedged honest rationale is more useful than a confident invented one.
