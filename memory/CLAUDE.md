# Memory

`schema/` is the memory contract and is tracked in git. The live Postgres data is not, and never belongs in the repo.

## What is persisted vs ephemeral

| Persisted (Postgres) | Ephemeral (Redis / in-process) |
| --- | --- |
| `sessions` — one per user conversation | Active session pointer |
| `runs` — one per pipeline execution, with status | Trace pub/sub channel |
| `criteria` — the parsed criteria for a run | In-flight scratchpad for the current run |
| `searches` — Scout search URL, total count, listings, and raw facet sections for a run | |
| `parcels` — candidates returned by Scout | Partial worker results before the run commits |
| `enrichments` — per-parcel facts + `sources_used` | |
| `scores` — score, per-dimension breakdown, rationale, highlights, drawbacks, not_assessed, considerations | |
| `trace_events` — the full replayable trace | |

Anything in the right column is gone on restart by design. If losing it would break a user-visible feature, it belongs on the left with a migration.

## Why this exists

The point of persisted memory is that a follow-up question does not re-run the pipeline. The Supervisor loads the last run's shortlist and answers directly, re-dispatching to Scout only when the criteria actually changed. Re-searching on every turn is the failure mode this layer exists to prevent.

`trace_events` is persisted as well as published so a page reload replays the full trace instead of showing an empty debug console.

## Rules

- A new persisted field requires a numbered migration in `schema/` **and** a row in the table above. Do not add a column by hand against a running database.
- Migrations are append-only and numbered sequentially (`006_<name>.sql`). Never edit a migration that has been applied.
- Everything keys off `run_id`, which the API mints at the edge. A row without a `run_id` cannot be traced and should not exist.
- Scratchpad state is in-process and never written to Postgres. If you find yourself persisting it, the run boundary is wrong.
- Do not store secrets, raw API keys, or full HTTP responses. Store the parsed facts and the source name.
