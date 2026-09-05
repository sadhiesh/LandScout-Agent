"""Criteria sufficiency gate for the Supervisor.

Decides whether there is enough to run a useful land search, and if not, what
single question to ask. Two stages, both cheap on the common path:

- Stage 1 runs before Scout and blocks only when the user has given no
  actionable signal at all. Searching on nothing wastes a request.
- Stage 2 runs after Scout and before the expensive Enricher and Scorer stages,
  using the real ``total_matching`` count to judge whether the result set is too
  broad for a top-10 shortlist to mean anything.

Stage 2 is deliberately grounded in a real count rather than the model's guess
about the user's wording. See ADR 0018 for why per-interpretation probing was
rejected.

Stage 1 fails open so intake cannot block all searching. Stage 2 fails safe:
analysis errors still stop oversized sets before enrichment and scoring.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agents.common.json_utils import extract_json

logger = logging.getLogger(__name__)

SKILL_PATH = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "criteria-sufficiency"
    / "SKILL.md"
)

# Fields that count as a real signal from the user, grouped by what they tell
# us. `state` is excluded on purpose: it is defaulted for nearly every request,
# so counting it would make every request look specified.
SIGNAL_FIELDS: dict[str, tuple[str, ...]] = {
    "location": ("county", "city", "region"),
    "budget": ("price_min", "price_max"),
    "acreage": ("acres_min", "acres_max"),
    "intent": (
        "property_types",
        "activities",
        "land_uses",
        "housing_types",
        "geographies",
        "keyword",
    ),
}

# Location fields worth confirming when the agent worked one out rather than
# the user stating it. Searching the wrong state silently wastes the whole run.
LOCATION_FIELDS = ("state", "county", "city", "region")

# What to offer dropping first when a search returns nothing, narrowest first.
# `keyword` leads because LandWatch matches it as literal free text, so a
# parcel with a creek is missed whenever the listing words it differently.
RELAX_PRIORITY = (
    "keyword",
    "property_types",
    "activities",
    "land_uses",
    "housing_types",
    "has_residence",
    "acres_max",
    "acres_min",
    "price_max",
    "price_min",
)

# Field names as they should read in a sentence to the user.
FIELD_LABELS = {
    "keyword": "keyword",
    "property_types": "property type",
    "activities": "activity",
    "land_uses": "land use",
    "housing_types": "housing type",
    "has_residence": "existing residence",
    "acres_min": "minimum acreage",
    "acres_max": "maximum acreage",
    "price_min": "minimum price",
    "price_max": "maximum price",
}

_AFFIRMATIVE = {
    "y", "ya", "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "k",
    "please", "please do", "yes please", "go ahead", "do it", "drop it",
    "remove it", "sounds good", "fine", "correct", "right", "confirm",
    "confirmed", "that's right", "thats right", "yes that's right",
    "yes thats right", "affirmative", "try again", "search again",
}

_SEARCH_CONFIRMATIONS = {
    "y", "ye", "yes", "yea", "yeah", "yep", "yup", "yes please", "yes run it", "yes please run it",
    "yes run the search", "yes please run the search", "ok", "okay", "k", "sure",
    "go ahead", "go ahead and search", "run it", "run the search", "search",
    "proceed", "confirm", "confirmed", "approve", "approved", "looks good",
    "looks good to me",
}

_SEARCH_REJECTIONS = {
    "n", "no", "nope", "cancel", "cancel search", "stop", "never mind",
    "nevermind", "do not search", "don't search",
}


@dataclass
class GateResult:
    """Outcome of a sufficiency check."""

    sufficient: bool
    question: Optional[str] = None
    missing: list[str] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)
    # Fields the user was asked to confirm. Answering without correcting them
    # counts as assent, so the next turn stops treating them as guesses.
    confirmed_fields: list[str] = field(default_factory=list)
    # A constraint offered for removal after a zero-result search, as
    # {"field": ..., "value": ...}. Applied only if the user agrees.
    relax_suggestion: Optional[dict[str, Any]] = None
    # Stage 2 inventory analysis shown beside un-enriched Scout candidates.
    common_conditions: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def is_affirmative(message: str) -> bool:
    """Whether a short reply reads as "yes".

    Deliberately strict: anything unrecognised is treated as a no, because
    the cost of wrongly dropping a filter the user cares about is higher than
    the cost of making them repeat themselves.
    """
    cleaned = message.strip().lower().rstrip(".!").strip()
    cleaned = re.sub(r"[^a-z' ]", "", cleaned).strip()
    return cleaned in _AFFIRMATIVE


def _normalize_search_confirmation(message: str) -> str:
    """Normalize a short criteria-confirmation reply for exact matching."""
    if re.search(r"\d", message):
        return ""
    cleaned = re.sub(r"[^a-z' ]", " ", message.strip().lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def is_search_confirmation(message: str) -> bool:
    """Whether a reply unambiguously approves the displayed full criteria."""
    return _normalize_search_confirmation(message) in _SEARCH_CONFIRMATIONS


def is_search_rejection(message: str) -> bool:
    """Whether a reply cancels a pending search without changing criteria."""
    return _normalize_search_confirmation(message) in _SEARCH_REJECTIONS


def inferred_locations(
    criteria: dict[str, Any],
    provenance: dict[str, str] | None,
) -> list[str]:
    """Location fields the agent worked out rather than the user stating."""
    if not provenance:
        return []
    return [
        name
        for name in LOCATION_FIELDS
        if criteria.get(name) and provenance.get(name) == "inferred"
    ]


def pick_relax_candidate(
    criteria: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Choose the constraint most likely to be responsible for zero results.

    Deterministic rather than model-chosen so the same empty search always
    gets the same explanation, and so the choice can be tested.
    """
    for name in RELAX_PRIORITY:
        value = criteria.get(name)
        if value not in (None, [], "", False):
            return {
                "field": name,
                "label": FIELD_LABELS.get(name, name),
                "value": value,
            }
    return None


def merge_criteria(
    prior: dict[str, Any],
    new: dict[str, Any],
    clear_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Combine criteria carried over from a clarifying turn with a fresh parse.

    Newly stated values win. Anything the user did not restate falls back to
    what they said before, so answering "about $400k" does not silently drop
    the county they named two turns ago. Explicit clears are applied to the
    prior criteria first, so an over-eager parser cannot erase a replacement
    value it supplied in the same patch. Neither input is mutated.
    """
    merged = dict(prior)
    for key in clear_fields or []:
        merged[key] = None

    # City, county, and region are alternative search scopes. When the user
    # supplies one, do not retain a different scope from an earlier turn.
    location_fields = ("city", "county", "region")
    supplied_locations = [
        key for key in location_fields if new.get(key) is not None
    ]
    for supplied in supplied_locations:
        for key in location_fields:
            if key != supplied:
                merged[key] = None

    for key, value in new.items():
        if value is not None:
            merged[key] = value
        elif key not in merged:
            merged[key] = None
    return merged


def count_signals(
    criteria: dict[str, Any],
    provenance: dict[str, str] | None = None,
) -> list[str]:
    """List which signal groups the user actually supplied.

    Uses the provenance map built during parsing so a defaulted value is not
    mistaken for something the user asked for. Without provenance, falls back
    to treating any non-null value as user-supplied.
    """
    present = []
    for group, fields in SIGNAL_FIELDS.items():
        for name in fields:
            value = criteria.get(name)
            if value in (None, [], ""):
                continue
            if provenance is not None and provenance.get(name) != "user":
                continue
            present.append(group)
            break
    return present


def missing_signals(
    criteria: dict[str, Any],
    provenance: dict[str, str] | None = None,
) -> list[str]:
    """Signal groups the user has not supplied. Complement of count_signals."""
    present = set(count_signals(criteria, provenance))
    return [group for group in SIGNAL_FIELDS if group not in present]


def stated_criteria(
    criteria: dict[str, Any],
    provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Only the values the user actually gave.

    Stage 1 judges whether the user said enough, so it must never be shown a
    defaulted or inferred value. Handed the full criteria dict it will read
    the config defaults as evidence and talk itself into searching — which is
    exactly how "need land" once became a $100k-$1M, 10-100 acre search.
    """
    return {
        key: value
        for key, value in criteria.items()
        if value not in (None, [], "")
        and (provenance is None or provenance.get(key) == "user")
    }


def _load_template(name: str) -> str:
    """Read one named prompt template out of the skill file.

    Templates are delimited by ``<!-- BEGIN name -->`` / ``<!-- END name -->``
    so surrounding prose can change without breaking extraction.
    """
    content = SKILL_PATH.read_text()
    match = re.search(
        rf"<!--\s*BEGIN {re.escape(name)}\s*-->\n(.*?)\n<!--\s*END {re.escape(name)}\s*-->",
        content,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"Template '{name}' not found in {SKILL_PATH}")
    return match.group(1).strip()


def _default_llm(prompt: str, provider: str | None = None, model: str | None = None) -> str:
    """Run a prompt through a small purpose-built CrewAI agent.

    Defined here rather than reusing ``create_supervisor_agent`` to avoid a
    circular import, and because writing a clarifying question is a different
    job from orchestrating a pipeline.
    
    Args:
        prompt: The prompt to send to the LLM
        provider: Optional LLM provider override
        model: Optional LLM model override
    """
    from crewai import Agent, Crew, Task

    from agents.common import build_llm

    agent = Agent(
        role="Land Search Intake Specialist",
        goal=(
            "Judge whether a land buyer has given enough to search on, and when "
            "they have not, ask the one question that unblocks them fastest"
        ),
        backstory=(
            "You take initial enquiries from land buyers. You know that people "
            "come to you wanting to see properties, not to fill in a form, so "
            "you ask for the least you need and let a broad search speak for "
            "itself whenever you can."
        ),
        tools=[],
        llm=build_llm(provider=provider, model=model),
        verbose=False,
        allow_delegation=False,
    )

    task = Task(
        description=prompt,
        expected_output="A single JSON object, no prose around it",
        agent=agent,
    )

    # orchestrate_pipeline already runs inside asyncio.to_thread, so a
    # synchronous kickoff is correct here.
    return str(Crew(agents=[agent], tasks=[task], verbose=False).kickoff())


def assess_criteria(
    criteria: dict[str, Any],
    provenance: dict[str, str] | None,
    user_message: str,
    round_num: int = 0,
    emitter: Any = None,
    llm_fn: Callable[[str], str] | None = None,
    confirm_inferred_locations: bool = True,
) -> GateResult:
    """Stage 1: is there enough here for a search to mean anything?

    Blocks only on a request with no actionable signal. Anything with a place,
    budget, size, or land type goes through to Scout, where Stage 2 judges it
    against the real match count instead of a guess.
    """
    import json

    from tools.scoring import get_gate_config

    config = get_gate_config()
    present = count_signals(criteria, provenance)
    inferred = (
        inferred_locations(criteria, provenance)
        if confirm_inferred_locations
        else []
    )
    enough_signals = len(present) >= config["min_signals"]

    if enough_signals and not (inferred and config["confirm_inferred_location"]):
        _emit(
            emitter,
            f"Criteria sufficient to search: {', '.join(present)}",
            {"stage": 1, "signals": present, "asked": False},
        )
        return GateResult(sufficient=True)

    if round_num >= config["max_rounds"]:
        assumptions = _apply_search_defaults(criteria, config["search_required"])
        _emit(
            emitter,
            f"Clarifying limit reached after {round_num} rounds; searching broad",
            {"stage": 1, "round": round_num, "assumptions": assumptions},
        )
        return GateResult(sufficient=True, assumptions=assumptions)

    missing = missing_signals(criteria, provenance)

    # There is enough to search on; the only open question is whether the
    # location the agent worked out is the one the user meant. Confirm it and
    # pick up one missing criterion in the same breath.
    if enough_signals:
        return _confirm_inference(
            criteria, inferred, missing, user_message, emitter, llm_fn
        )

    try:
        # Only what the user said — never the defaults or our own inferences.
        stated = stated_criteria(criteria, provenance)
        prompt = (
            _load_template("stage1")
            .replace("{user_message}", user_message)
            .replace(
                "{stated_json}",
                json.dumps(stated, indent=2, default=str)
                if stated
                else "nothing at all",
            )
        )
        parsed = extract_json((llm_fn or _default_llm)(prompt))
        if not isinstance(parsed, dict):
            raise ValueError("Criteria assessment did not return a JSON object")
    except Exception as e:
        # Fail open. A gate that cannot reason must not stop a search.
        logger.warning(f"Stage 1 assessment failed, proceeding to search: {e}")
        _emit(
            emitter,
            "Sufficiency check failed; proceeding to search",
            {"stage": 1, "error": str(e), "failed_open": True},
        )
        return GateResult(sufficient=True)

    sufficient = bool(parsed.get("sufficient", True))
    question = parsed.get("question")

    _emit(
        emitter,
        parsed.get("reasoning", "Assessed criteria sufficiency"),
        {
            "stage": 1,
            "round": round_num,
            "interpretations": parsed.get("interpretations", []),
            "sufficient": sufficient,
            "missing": parsed.get("missing_critical", missing),
        },
    )

    if sufficient or not question:
        return GateResult(sufficient=True)

    return GateResult(
        sufficient=False,
        question=question,
        missing=parsed.get("missing_critical", missing),
    )


def _confirm_inference(
    criteria: dict[str, Any],
    inferred: list[str],
    missing: list[str],
    user_message: str,
    emitter: Any = None,
    llm_fn: Callable[[str], str] | None = None,
) -> GateResult:
    """Ask the user to confirm a location the agent worked out for itself."""
    summary = ", ".join(f"{name} = {criteria.get(name)}" for name in inferred)

    try:
        prompt = (
            _load_template("stage1_confirm")
            .replace("{user_message}", user_message)
            .replace("{inferred_summary}", summary)
            .replace("{missing_fields}", ", ".join(missing) or "nothing else")
        )
        parsed = extract_json((llm_fn or _default_llm)(prompt))
        if not isinstance(parsed, dict):
            raise ValueError("Inference confirmation did not return a JSON object")
    except Exception as e:
        logger.warning(f"Inference confirmation failed, proceeding to search: {e}")
        _emit(
            emitter,
            "Confirmation check failed; proceeding to search",
            {"stage": 1, "error": str(e), "failed_open": True},
        )
        return GateResult(sufficient=True)

    question = parsed.get("question")
    if not question:
        return GateResult(sufficient=True)

    _emit(
        emitter,
        parsed.get("reasoning", f"Confirming inferred {summary}"),
        {"stage": 1, "inferred": inferred, "missing": missing, "asked": True},
    )

    return GateResult(
        sufficient=False,
        question=question,
        missing=missing,
        confirmed_fields=inferred,
    )


def assess_no_results(
    criteria: dict[str, Any],
    round_num: int = 0,
    emitter: Any = None,
    llm_fn: Callable[[str], str] | None = None,
) -> GateResult:
    """Handle a search that matched nothing by offering to drop a constraint.

    The mirror of ``assess_breadth``. Zero results is the worse dead end,
    because the user has nothing at all to act on, and the fix is always to
    remove a constraint rather than add one.
    """
    import json

    from tools.scoring import get_gate_config

    config = get_gate_config()

    if not config["offer_relax_on_zero"]:
        return GateResult(sufficient=True)

    candidate = pick_relax_candidate(criteria)
    if not candidate:
        # Nothing to drop — the search was already as loose as it gets, so
        # there genuinely is no inventory to show.
        _emit(
            emitter,
            "No matches and no constraint left to relax",
            {"stage": 2, "total_matching": 0, "asked": False},
        )
        return GateResult(sufficient=True)

    try:
        prompt = (
            _load_template("stage2_relax")
            .replace("{criteria_json}", json.dumps(criteria, indent=2, default=str))
            .replace("{relax_field}", candidate["label"])
            .replace("{relax_value}", str(candidate["value"]))
        )
        parsed = extract_json((llm_fn or _default_llm)(prompt))
        if not isinstance(parsed, dict):
            raise ValueError("Relax suggestion did not return a JSON object")
    except Exception as e:
        logger.warning(f"Relax suggestion failed; using fallback wording: {e}")
        _emit(
            emitter,
            "Relax wording failed; still offering the deterministic relaxation",
            {"stage": 2, "error": str(e), "failed_safe": True},
        )
        return GateResult(
            sufficient=False,
            question=(
                f"Nothing matched. The {candidate['label']} filter "
                f"({candidate['value']}) may be too restrictive. "
                "Would you like me to remove it from the criteria? "
                "I will show the revised criteria for confirmation."
            ),
            relax_suggestion=candidate,
        )

    question = parsed.get("question") or (
        f"Nothing matched. The {candidate['label']} filter "
        f"({candidate['value']}) may be too restrictive. "
        "Would you like me to remove it from the criteria? "
        "I will show the revised criteria for confirmation."
    )

    _emit(
        emitter,
        parsed.get("reasoning", f"No matches; {candidate['label']} is the likely cause"),
        {
            "stage": 2,
            "total_matching": 0,
            "relax_field": candidate["field"],
            "relax_value": candidate["value"],
        },
    )

    return GateResult(
        sufficient=False,
        question=question,
        relax_suggestion=candidate,
    )


def apply_clarification_answer(
    criteria: dict[str, Any],
    provenance: dict[str, str],
    pending: dict[str, Any],
    user_message: str,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Fold the user's reply to a clarifying question into the criteria.

    Handles the two things a reply can do that a plain merge cannot:
    accepting an assumption, and agreeing to drop a constraint. Returns new
    dicts plus notes describing what changed, for the trace.
    """
    criteria = dict(criteria)
    provenance = dict(provenance)
    notes: list[str] = []

    # Asked about an assumption and not corrected — treat that as assent so
    # the same question is never put twice.
    for name in pending.get("confirmed_fields") or []:
        if provenance.get(name) == "inferred":
            provenance[name] = "user"
            notes.append(f"confirmed {name} = {criteria.get(name)}")

    suggestion = pending.get("relax_suggestion")
    if suggestion and is_affirmative(user_message):
        name = suggestion["field"]
        criteria[name] = None
        provenance[name] = "relaxed"
        notes.append(f"dropped {suggestion.get('label', name)} filter")

    return criteria, provenance, notes


def assess_breadth(
    criteria: dict[str, Any],
    parcels: list[dict[str, Any]],
    candidate_limit: int,
    total_matching: int | None = None,
    provenance: dict[str, str] | None = None,
    round_num: int = 0,
    emitter: Any = None,
    llm_fn: Callable[[str], str] | None = None,
) -> GateResult:
    """Stage 2: stop an oversized returned set before enrichment and scoring.

    This limit is hard. If inventory analysis fails, the gate still returns a
    deterministic narrowing question instead of letting too many parcels reach
    the expensive stages.
    """
    import json

    returned_count = len(parcels)

    if returned_count <= candidate_limit:
        _emit(
            emitter,
            f"{returned_count} returned candidates fit the enrichment limit",
            {
                "stage": 2,
                "returned_count": returned_count,
                "candidate_limit": candidate_limit,
                "asked": False,
            },
        )
        return GateResult(sufficient=True)

    common_conditions = _fallback_common_conditions(parcels)
    recommendations = [
        f"Select up to {candidate_limit} parcels from these candidates.",
        "Or narrow the search by location, budget, acreage, or property type.",
    ]
    total_str = f"{total_matching:,}" if total_matching else "many"
    fallback_question = (
        f"I found {total_str} properties matching your criteria, showing {returned_count} "
        f"as candidates. For effective enrichment, please either select up to {candidate_limit} "
        "parcels to analyze in depth, or narrow your criteria (price, acreage, location, or property type)."
    )

    try:
        prompt = (
            _load_template("stage2")
            .replace("{returned_count}", f"{returned_count:,}")
            .replace("{candidate_limit}", str(candidate_limit))
            .replace(
                "{total_matching}",
                f"{total_matching:,}" if total_matching is not None else "unknown",
            )
            .replace("{criteria_json}", json.dumps(criteria, indent=2, default=str))
            .replace(
                "{candidate_json}",
                json.dumps(
                    [_candidate_summary(parcel) for parcel in parcels],
                    indent=2,
                    default=str,
                ),
            )
        )
        parsed = extract_json((llm_fn or _default_llm)(prompt))
        if not isinstance(parsed, dict):
            raise ValueError("Inventory analysis did not return a JSON object")
    except Exception as e:
        logger.warning(f"Stage 2 inventory analysis failed; using fallback: {e}")
        _emit(
            emitter,
            "Inventory analysis failed; keeping the enrichment guard closed",
            {
                "stage": 2,
                "error": str(e),
                "returned_count": returned_count,
                "candidate_limit": candidate_limit,
                "failed_safe": True,
            },
        )
        return GateResult(
            sufficient=False,
            question=fallback_question,
            common_conditions=common_conditions,
            recommendations=recommendations,
        )

    question = parsed.get("question") or fallback_question
    parsed_conditions = parsed.get("common_conditions")
    parsed_recommendations = parsed.get("recommendations")
    if isinstance(parsed_conditions, list):
        common_conditions = [
            str(item) for item in parsed_conditions if str(item).strip()
        ] or common_conditions
    if isinstance(parsed_recommendations, list):
        recommendations = [
            str(item) for item in parsed_recommendations if str(item).strip()
        ] or recommendations

    _emit(
        emitter,
        parsed.get(
            "reasoning",
            f"{returned_count} candidates exceed the {candidate_limit}-parcel limit",
        ),
        {
            "stage": 2,
            "round": round_num,
            "returned_count": returned_count,
            "candidate_limit": candidate_limit,
            "total_matching": total_matching,
            "common_conditions": common_conditions,
            "recommendations": recommendations,
        },
    )

    return GateResult(
        sufficient=False,
        question=question,
        common_conditions=common_conditions,
        recommendations=recommendations,
    )


def _candidate_summary(parcel: dict[str, Any]) -> dict[str, Any]:
    """Return the compact, factual subset the Stage 2 LLM may reason over."""
    location = parcel.get("location") or {}
    info = parcel.get("basic_info") or {}
    return {
        "property_id": parcel.get("property_id"),
        "city": location.get("city"),
        "county": location.get("county"),
        "state": location.get("state"),
        "price": info.get("price"),
        "acres": info.get("acres"),
        "price_per_acre": info.get("price_per_acre"),
        "property_types": info.get("property_types") or [],
    }


def _fallback_common_conditions(parcels: list[dict[str, Any]]) -> list[str]:
    """Build useful inventory observations without an LLM."""
    summaries = [_candidate_summary(parcel) for parcel in parcels]
    conditions: list[str] = []

    cities = Counter(item["city"] for item in summaries if item.get("city"))
    if cities:
        city, count = cities.most_common(1)[0]
        conditions.append(f"{count} of {len(parcels)} parcels are in {city}.")

    prices = [
        item["price"]
        for item in summaries
        if isinstance(item.get("price"), (int, float))
    ]
    if prices:
        conditions.append(
            f"List prices range from ${min(prices):,.0f} to ${max(prices):,.0f}."
        )

    acres = [
        item["acres"]
        for item in summaries
        if isinstance(item.get("acres"), (int, float))
    ]
    if acres:
        conditions.append(
            f"Parcel sizes range from {min(acres):g} to {max(acres):g} acres."
        )

    return conditions or [f"Scout returned {len(parcels)} selectable parcels."]


def _apply_search_defaults(
    criteria: dict[str, Any],
    search_required: list[str],
) -> dict[str, Any]:
    """Fill only the fields a search cannot be formed without.

    Mutates ``criteria`` in place so the caller searches with the filled
    values, and returns just what was applied so the user can be told.

    Deliberately narrow. Defaulting a price or acreage range would add a
    constraint the user never asked for, and a constraint hides parcels; a
    broad search that returns too much is the recoverable failure.
    """
    from tools.scoring import get_defaults

    defaults = get_defaults()
    applied = {}
    for name in search_required:
        if criteria.get(name) is None and name in defaults:
            criteria[name] = defaults[name]
            applied[name] = defaults[name]
    return applied


def _emit(emitter: Any, summary: str, data: dict[str, Any]) -> None:
    """Emit a thought trace event, tolerating a missing or broken emitter."""
    if emitter is None:
        return
    try:
        emitter.emit("thought", summary, data)
    except Exception as e:
        logger.debug(f"Trace emission failed in criteria gate: {e}")
