# Scoring

Deterministic weighted scoring of enriched parcels. Produces a 0–100 score plus a per-dimension breakdown.

## The boundary that matters

The math lives here. The prose lives in the Scorer agent. No LLM call happens in this folder, and no scoring weight is ever applied inside a prompt. This split is what makes a rationale auditable: every sentence the Scorer writes must trace back to a number produced here.

## Structure

- `weights.py` — weights, the `cad:` and `presentation:` tunables, defaults, and the gate config, all loaded from `config/criteria.yaml` so no number is tunable only by a code change.
- `score_parcel.py` — pure function: enriched parcel + criteria → `{score, breakdown, highlights, drawbacks, not_assessed}`. No I/O, no network, no logging side effects. Highlights and drawbacks are deterministically derived from dimension scores using thresholds in `presentation:`.

## Dimensions

Nine, each normalizing to 0–1 before weighting so a dimension cannot dominate by unit scale.

| Dimension | Reads |
| --- | --- |
| `value_vs_comps` | Ask per acre against a benchmark, via the cascade below |
| `criteria_match` | Price, property types, and CAD-derived jurisdiction |
| `acreage_fit` | CAD `landSizeAcres` (falling back to the listing), discounted on GIS/appraised disagreement |
| `land_use_fit` | `landTypeCode`, `landCategoryCodes`, `propSubType`, `improved` |
| `developability` | `compactness`, `propSplitFromPID`, `protestCode`, `udiPropFlag` |
| `access_and_utilities` | LandWatch description keywords |
| `tax_burden` | `entityCodes`, MUD/TIF/SBCL flags, ag valuation and rollback exposure |
| `water_and_terrain` | LandWatch description keywords |
| `market_signal` | Days on market, price cuts, `held_years`, `owner_occupied` |

### The value_vs_comps cascade

Three bases in descending order of authority: the CCAD median for the parcel's own `nbhdCode` cohort, then the parcel's own appraised market value, then the LandWatch-derived county median. With none of them the dimension raises and is skipped — it does **not** fall back to a neutral 0.5, which would let a dead data source masquerade as an average parcel.

The first two bases anchor at 1.0 (asking exactly the appraised value scores 1.0, `value_ratio_ceiling` times it scores 0). The third compares against a median of *asks* rather than appraisals, so it keeps its own 0.5–2.0 band.

### CAD-only dimensions

`tax_burden`, `land_use_fit`, and `developability` read county appraisal data, which exists only for Collin County. Everywhere else they skip and the remaining weights renormalize. A non-Collin parcel is therefore scored on roughly half the total weight — correct under the missing-data rule, but it makes cross-county comparison weaker than the single number suggests.

`udiPropFlag` is the one hard disqualifier: a fractional undivided interest scores `developability` at 0.0 rather than taking a discount. Everything else is a soft penalty.

## Rules

- Scoring is a pure function. Same inputs, same output, every time — it must be reproducible from the persisted enrichment alone.
- A missing enrichment field is not a zero. Renormalize across the dimensions that do have data and record which were skipped; scoring an absent fact as "bad" quietly punishes parcels for a dead API.
- Never hardcode a weight or threshold. If a number is not in `config/criteria.yaml`, it does not belong in the score or presentation.
- The breakdown, highlights, drawbacks, and not_assessed lists are part of the output contract, not debug aids. The Scorer agent and both UIs depend on them.
- Changing a weight or adding a dimension changes every historical ranking. Record it in `docs/decisions/` and version the criteria.
- Highlights and drawbacks are ranked by `weight * abs(raw_score - 0.5)` — what actually moved the score — and are capped at the limits in `presentation:`. Hard zeros (like `udiPropFlag`) pin to the top of drawbacks.
