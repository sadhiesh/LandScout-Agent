# Scorer Agent

Port 8004. Ranks enriched parcels and writes the rationale for each.

**Owns:** `score_parcel` in `tools/scoring/`, and the `scoring-methodology` skill.

**Does not own:** search, enrichment, or any write-capable tool.

## Contract

- Receives from Supervisor: `{enriched_parcels, criteria}`.
- Returns to Supervisor: parcels with a 0–100 score, a per-dimension breakdown, and a written rationale each.

## The rule that matters

**Scoring is deterministic; only the prose is generated.** The weighted math happens in `tools/scoring/`, not in the model. The LLM's only job is turning the resulting breakdown into readable English.

A rationale may cite only what appears in that parcel's score breakdown and enrichment fields. Citing a specific driver ("$4,100/acre against a county median of $6,800") is correct; a generic claim ("strong growth potential") that no field supports is a defect, not a style issue. If the breakdown does not justify a ranking, say the data is thin rather than inventing support for it.

## Rules

- Weights live in `config/criteria.yaml`. Never hardcode a weight in the agent or the prompt.
- Load `skills/scoring-methodology/SKILL.md` when scoring or explaining a score; do not restate the rubric in the agent prompt.
- Score every parcel the Enricher returned, including poor ones. A low score with a clear reason is useful output.
