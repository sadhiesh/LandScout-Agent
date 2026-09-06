# Criteria Sufficiency Skill

## Purpose

Decide whether the Supervisor has enough to run a useful land search, and if not, write the one question most worth asking the user. Two stages, each with its own prompt template below.

Parsing raw text into criteria is a different job — see `skills/criteria-parsing/SKILL.md`.

## Usage

Loaded by `agents/supervisor/criteria_gate.py`. Templates are delimited by `BEGIN`/`END` HTML comments and extracted by name, so headings and prose around them can change freely without breaking the loader.

Both templates are invoked only when a cheap deterministic check has already decided a question might be warranted. Neither runs on the common path.

## Stage 1 — pre-search sufficiency

Runs before Scout, only when the user has given no actionable signal at all (no location, budget, acreage, or intent). Searching on nothing wastes a request and returns noise.

Bias strongly toward proceeding. The user came for parcels, not an interview. Ask only when a search genuinely cannot mean anything.

The template is given **only the fields the user actually stated**, never the full criteria dict. Shown config defaults, the model reads them as evidence and reasons its way into searching — "need land" once became a Texas, $100k–$1M, 10–100 acre, three-property-type search on exactly that mistake.

<!-- BEGIN stage1 -->


A user is searching for land to buy. Decide whether their request is specific
enough to run a useful search.

Their message:
"{user_message}"

What they have actually told you, and nothing else:
{stated_json}

Treat that list as complete. Anything absent from it, the user has not said —
the system may have a default or a guess on file for it, but a default is not
something the user asked for and must not count as evidence here.

Think it through in this order:

1. Restate what the user actually asked for, in one sentence.
2. List 2-3 genuinely different things they could mean. If the request only has
  one sensible reading, say so and list just that one.
3. If the readings differ, name the single piece of information that would best
  tell them apart.
4. Decide: is there enough here to run a search that returns something useful?

Rules:

- Bias toward YES. A broad search that returns results beats an interrogation.
- Answer YES if they gave ANY of: a place, a budget, a size, or a type of land.
- Answer NO only when the request is so open-ended that any parcel would match.
- If NO, write ONE friendly question. Ask for at most two things. Do not present
a checklist of every field you could fill.
- Never invent a constraint the user did not state.

Return ONLY this JSON:
{"reasoning": "<your step 1-4 thinking, 2-3 sentences>",
 "interpretations": ["<reading 1>", "<reading 2>"],
 "sufficient": true|false,
 "missing_critical": ["location"|"budget"|"acreage"|"intent"],
 "question": "<your question, or null if sufficient>"}

<!-- END stage1 -->


## Stage 1b — confirm an inferred location

Available to callers that do not provide a separate confirmation step when the
agent worked out a location the user never stated — "McKinney" implies Texas,
but the user did not say Texas. The Supervisor disables this prompt because its
mandatory complete-criteria confirmation covers the same assumption without
asking twice.

Fold the confirmation together with the single most useful missing criterion so this costs one turn, not two.

<!-- BEGIN stage1_confirm -->


A user is searching for land. From their message you worked out a location
they did not actually state, and you should check it before searching.

Their message:
"{user_message}"

You assumed: {inferred_summary}
They also have not told you: {missing_fields}

Write ONE short message that:

1. Confirms your assumption in a way they can correct in a few words.
2. Asks for at most ONE of the things they have not told you — whichever
  would most improve the results. Budget and acreage help most.

Rules:

- Lead with the assumption. Make it easy to say "yes, that's right".
- Do not list every field you could fill. One follow-up, not a form.
- Be warm and brief. Two sentences at most.
- Do not apologise or explain how the system works.

Return ONLY this JSON:
{"reasoning": "<why this is worth confirming, 1 sentence>",
 "question": "<short confirmation question>"}

<!-- END stage1_confirm -->


## Stage 2b — no results at all

Runs when the search returned nothing. Zero results is the mirror of too-broad and the worse dead end, because the user has nothing to act on.

The fix here is to *remove* a constraint, never to add one. The caller has already picked the filter most likely to blame; the prompt's job is to offer dropping it in a way the user can accept with one word.

<!-- BEGIN stage2_relax -->


A user's land search returned no results at all.

The search that was run:
{criteria_json}

The filter most likely to blame is {relax_field}, currently set to
"{relax_value}". It is the narrowest thing in this search.

Write ONE short message that:

1. Tells them nothing matched.
2. Names {relax_field} as the likely reason, in plain language rather than
  as a field name.
3. Offers to remove it from the criteria, so they can accept with one word.
  Explain that the revised criteria will be shown for confirmation before the
  next search.

Rules:

- Do not ask them to add a budget or acreage. Nothing matched, so narrowing
further is the wrong direction.
- Do not suggest dropping anything other than {relax_field}.
- Be warm and brief. Two or three sentences.

Return ONLY this JSON:
{"reasoning": "<why this filter is the likely culprit, 1 sentence>",
 "question": "<short question offering to remove the filter>"}

<!-- END stage2_relax -->


## Stage 2 — facet-guided narrowing

Runs after Scout returns, before the expensive Enricher and Scorer stages, when LandWatch still reports more matches than the configured shortlist size. It receives only validated facet options derived from LandWatch's contextual counts and must choose among those safe options by ID.

<!-- BEGIN stage2 -->


A user's land search has {total_matching} total matches. Only {candidate_limit}
or fewer may proceed to enrichment and scoring.

The current search criteria:
{criteria_json}

Validated narrowing options derived from LandWatch facets:
{refinement_options_json}

Identify common patterns in those options and pick 3-5 useful option IDs that
would materially reduce the count. Then write one short question asking the
user to choose one of the suggested filters or type a tighter preference.

Rules:

- You MUST use only option IDs that appear in `refinement_options_json`.
- Prefer a mix of dimensions such as location, budget, acreage, residence, or
  property type when the data supports it.
- Base every common condition on the validated options and counts. Do not
  invent facts.
- Do not mention parcel selection. The user must narrow further until the total
  match count is {candidate_limit} or fewer.
- Be warm and brief. Do not apologise or explain the pipeline.

Return ONLY this JSON:
{"reasoning": "<why these cuts are useful, 1-2 sentences>",
 "common_conditions": ["<observed pattern>", "<observed pattern>"],
 "recommended_option_ids": ["<option id>", "<option id>"],
 "question": "<short narrowing question>"}

<!-- END stage2 -->


## Output contract

Both templates return JSON parsed through `agents.common.json_utils.extract_json`, which tolerates markdown fences and prose wrapping (ADR 0015).

If parsing fails or the LLM errors, the gate **fails open**: it reports sufficient and lets the search proceed. A broken gate must never block a user from searching.

## Examples



### Stage 1, sufficient

**Input:** "20 acres near McKinney", stated `{"city": "mckinney", "acres_min": 20}`

```json
{
  "reasoning": "They named a city and a size, so the search has real constraints to work with. The only ambiguity is intended use, which does not block a search.",
  "interpretations": ["Homesite acreage near McKinney", "Investment land in the McKinney growth corridor"],
  "sufficient": true,
  "missing_critical": [],
  "question": null
}
```



### Stage 1, insufficient

**Input:** "I want to buy some land", stated `nothing at all`

```json
{
  "reasoning": "No place, budget, size, or type of land. Every parcel in the database matches this equally, so a search would return noise.",
  "interpretations": ["Recreational land for personal use", "Land as an investment hold", "A homesite to build on"],
  "sufficient": false,
  "missing_critical": ["location", "budget"],
  "question": "Happy to help you find land. Whereabouts are you looking, and do you have a budget in mind?"
}
```



### Stage 1b, confirming an inference

**Input:** "Recreational land in McKinney with creek access", inferred `state: texas`

```json
{
  "reasoning": "McKinney is almost certainly the Texas one, but the user never said so and searching the wrong state would waste the run.",
  "question": "I'll take that as McKinney, Texas — say the word if you meant elsewhere. Do you have a budget range in mind?"
}
```



### Stage 2b, nothing matched

**Input:** criteria with `keyword: "creek access"`, `city: mckinney`, `property_types: ["recreational"]`, 0 results

```json
{
  "reasoning": "The free-text keyword filter is the narrowest constraint here and rules out listings that simply describe a creek differently.",
  "question": "Nothing came back for that one. The \"creek access\" wording is the likely culprit — LandWatch matches it literally. Want me to remove it and show you the revised criteria to confirm?"
}
```



### Stage 2, too many returned candidates

**Input:** 25 returned candidates spanning $120k–$900k and 5–80 acres

```json
{
  "reasoning": "The returned set separates cleanly by both price and acreage, so either preference would materially reduce the candidates without guessing which parcels are best.",
  "common_conditions": ["Most returned parcels are between 10 and 40 acres.", "Prices span from $120,000 to $900,000."],
  "recommendations": ["Set a maximum purchase price.", "Choose a tighter acreage range."],
  "question": "Scout returned 25 parcels, and I can fully analyze up to 10. Select the parcels you want, or tell me a tighter budget or acreage range."
}
```

