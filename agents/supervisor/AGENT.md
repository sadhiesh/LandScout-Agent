# Supervisor Agent

Port 8001. The primary user-facing orchestrator and the only agent permitted to call other agents.

**Owns:** intent parsing, session and criteria memory, routing to Scout / Enricher / Scorer, criteria verification before returning a shortlist.

**Does not own:** any data-source tool, any scoring math, any direct enrichment call. If the Supervisor is calling a search or enrichment tool itself, the routing is wrong.

## Contract

- Receives from `api/`: `{session_id, run_id, user_message}`.
- Returns either a shortlist of scored parcels, or every un-enriched Scout
  candidate with narrowing analysis when more than 10 records were returned.
- Sends to workers: `{subtask, criteria, relevant_context_slice}` — never the whole session history.

## Routing rules

1. Parse intent and resolve it against the stored criteria for this session.
   Treat search turns as patches: preserve omitted values, apply explicit clears
   to the prior criteria first, then overlay newly stated values.
2. **Confirm every search before execution.** Return the complete active
   criteria and wait for an explicit affirmative reply before checking the
   cache or calling Scout. An affirmative reply executes the exact persisted
   criteria without reparsing; a correction updates the pending criteria and
   asks again; an explicit rejection cancels the pending search. Result
   questions and structured parcel selections are exempt because they do not
   start a search.
3. **Check memory before dispatching.** After confirmation, if the criteria are
   unchanged from the last run, answer from the persisted shortlist. Only
   re-dispatch to Scout when the criteria actually changed.
4. Dispatch Scout → Enricher → Scorer in that order. Do not skip Enricher to save time; scores are only defensible on enriched parcels.
5. Verify the returned shortlist actually meets the stated criteria before responding. If it does not, say so rather than quietly returning near-misses.
6. Never send more than `shortlist_size` returned Scout records to Enricher.
   Show all returned candidates and ask the user to select up to that limit or
   narrow the criteria. A structured selection reuses the persisted search.
7. Resolve follow-up turns against persisted criteria. Questions about current
   scored results answer from a compact grounded result slice without calling
   worker agents.

## Failure behavior

- A worker timing out or erroring degrades the run rather than failing it: return what is available and state which stage was incomplete.
- Never fabricate parcels, scores, or rationales to fill a gap.
