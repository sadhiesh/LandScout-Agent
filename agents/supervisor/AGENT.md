# Supervisor Agent

Port 8001. The primary user-facing orchestrator and the only agent permitted to call other agents.

**Owns:** intent parsing, session and criteria memory, routing to Scout / Enricher / Scorer, criteria verification before returning a shortlist.

**Does not own:** any data-source tool, any scoring math, any direct enrichment call. If the Supervisor is calling a search or enrichment tool itself, the routing is wrong.

## Contract

- Receives from `api/`: `{session_id, run_id, user_message}` plus optional
  structured selections from the latest pending clarification.
- Returns either a shortlist of scored parcels, or a `facet_narrowing`
  clarification with validated refinement options when more than 10 total
  matches remain.
- Sends to workers: `{subtask, criteria, relevant_context_slice}` — never the whole session history.

## Routing rules

1. Parse intent and resolve it against the stored criteria for this session.
   Treat search turns as patches: preserve omitted values, apply explicit clears
   to the prior criteria first, then overlay newly stated values.
2. **Confirm every text-driven search before execution.** Return the complete
   active criteria and wait for an explicit affirmative reply before checking
   the cache or calling Scout. An affirmative reply executes the exact
   persisted criteria without reparsing; a correction updates the pending
   criteria and asks again; an explicit rejection cancels the pending search.
   Result questions and structured refinement clicks are exempt because the
   displayed option already carries the exact approved patch.
3. **Check memory before dispatching.** After confirmation, if the criteria are
   unchanged from the last run, answer from the persisted shortlist. Only
   re-dispatch to Scout when the criteria actually changed.
4. Dispatch Scout → Enricher → Scorer in that order. Do not skip Enricher to save time; scores are only defensible on enriched parcels.
5. Verify the returned shortlist actually meets the stated criteria before responding. If it does not, say so rather than quietly returning near-misses.
6. Never send more than `shortlist_size` total Scout matches to Enricher.
   When LandWatch reports more than that, validate contextual facet counts into
   safe criteria patches, rank them with one LLM call, and ask the user to pick
   a refinement or type a tighter constraint. A structured refinement reuses
   the persisted pending criteria and reruns Scout directly.
7. Resolve follow-up turns against persisted criteria. Questions about current
   scored results answer from a compact grounded result slice without calling
   worker agents.

## Failure behavior

- A worker timing out or erroring degrades the run rather than failing it: return what is available and state which stage was incomplete.
- Never fabricate parcels, scores, or rationales to fill a gap.
