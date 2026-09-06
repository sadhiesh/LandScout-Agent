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
from landwatch.filters import FILTER_CATALOG, FilterKind
from landwatch.vocab import slugify

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

# The narrowing dimensions an investor reaches for first — acreage, price,
# location, and residence. These always render in the facet-narrowing UI in
# full; everything else (property type, activities, land use, ...) is a
# secondary/long-tail facet that only shows up when it earns its place, via
# `_trim_secondary_options` below. Keep this in sync with `preferred_order`
# in `_build_refinement_options`.
PRIMARY_FACET_SECTIONS = {"City", "County", "Region", "Price", "Parcel Size", "Residence"}

# Above this many total options, a flat list stops being scannable, so
# secondary-tier facets get curated down to the LLM's picks (see
# `_trim_secondary_options`). Below it, nothing is hidden — there is nothing
# to declutter.
WIDE_RESULT_THRESHOLD = 8

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

# Purpose/intent words that have no place as a literal LandWatch listing-text
# filter. LandWatch's keyword field does a full-text search over listing titles
# and descriptions, so "investment" rarely appears verbatim in a listing and
# silently kills result counts. These words describe *why* the buyer wants the
# land, not *what* the land is like. The list is conservative: only terms where
# the buyer's motive is the sole reasonable reading (not genuine land features).
GENERIC_KEYWORD_TERMS: frozenset[str] = frozenset({
    "investment",
    "investing",
    "resale",
    "resell",
    "reselling",
    "flip",
    "flipping",
    "profit",
    "personal use",
    "quick sale",
    "cash buyer",
    "cash offer",
})


def strip_generic_keyword_terms(keyword: str | None) -> str | None:
    """Remove generic purpose/intent words from a keyword string.

    Applies an exact whole-word/phrase match (case-insensitive) against
    GENERIC_KEYWORD_TERMS so that a buyer saying "its for investment" does not
    pollute the Scout search keyword with "investment".

    Multi-word denylist phrases (e.g. "personal use") are checked as substrings
    of the full keyword string after single-word terms are stripped token by
    token. Genuine feature words that happen to contain a denylist token are
    left alone because matching is whole-word or whole-phrase only.

    Returns None when nothing useful remains.
    """
    if not keyword:
        return None

    # Separate single-word entries from multi-word phrases for efficient matching.
    single_terms = {t for t in GENERIC_KEYWORD_TERMS if " " not in t}
    phrase_terms = {t for t in GENERIC_KEYWORD_TERMS if " " in t}

    # Token-level removal for single-word entries (whole-word match only).
    tokens = keyword.split()
    tokens = [t for t in tokens if t.lower() not in single_terms]
    result = " ".join(tokens)

    # Phrase-level removal — case-insensitive substring of the joined result.
    for phrase in phrase_terms:
        result = re.sub(
            r"(?i)\b" + re.escape(phrase) + r"\b",
            "",
            result,
        )

    # Collapse excess whitespace left by removed phrases.
    result = " ".join(result.split())

    return result if result else None


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
    refinement_options: list[dict[str, Any]] = field(default_factory=list)


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
            # Special case: accumulate keywords instead of replacing
            if key == "keyword" and merged.get("keyword"):
                existing = merged["keyword"]
                # Deduplicate while preserving order
                all_keywords = [existing, value]
                seen = set()
                unique_keywords = []
                for kw in all_keywords:
                    kw_lower = kw.lower().strip()
                    if kw_lower and kw_lower not in seen:
                        seen.add(kw_lower)
                        unique_keywords.append(kw)
                # Strip generic terms from the accumulated result so a bad word
                # from a prior turn cannot survive across subsequent merges.
                merged[key] = strip_generic_keyword_terms(
                    " ".join(unique_keywords)
                )
            else:
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
    facets: list[dict[str, Any]] | None = None,
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
    effective_total = total_matching if total_matching is not None else returned_count

    if effective_total <= candidate_limit:
        _emit(
            emitter,
            f"{effective_total} matches fit the enrichment limit",
            {
                "stage": 2,
                "returned_count": returned_count,
                "total_matching": total_matching,
                "candidate_limit": candidate_limit,
                "asked": False,
            },
        )
        return GateResult(sufficient=True)

    refinement_options = _build_refinement_options(criteria, facets or [], effective_total)
    common_conditions = _fallback_common_conditions(refinement_options, effective_total)
    recommendations = _fallback_recommendations(refinement_options)
    total_str = f"{effective_total:,}" if effective_total else "many"
    fallback_question = (
        f"LandWatch shows {total_str} matching properties. Add one more filter below, "
        "or tell me a tighter location, budget, acreage, or property type so I can narrow the search."
    )

    try:
        prompt = (
            _load_template("stage2")
            .replace("{returned_count}", f"{returned_count:,}")
            .replace("{candidate_limit}", str(candidate_limit))
            .replace(
                "{total_matching}",
                f"{effective_total:,}" if effective_total is not None else "unknown",
            )
            .replace("{criteria_json}", json.dumps(criteria, indent=2, default=str))
            .replace(
                "{refinement_options_json}",
                json.dumps(refinement_options, indent=2, default=str),
            )
        )
        parsed = extract_json((llm_fn or _default_llm)(prompt))
        if not isinstance(parsed, dict):
            raise ValueError("Refinement analysis did not return a JSON object")
    except Exception as e:
        logger.warning(f"Stage 2 inventory analysis failed; using fallback: {e}")
        _emit(
            emitter,
            "Facet analysis failed; keeping the narrowing guard closed",
            {
                "stage": 2,
                "error": str(e),
                "returned_count": returned_count,
                "total_matching": effective_total,
                "candidate_limit": candidate_limit,
                "failed_safe": True,
            },
        )
        return GateResult(
            sufficient=False,
            question=fallback_question,
            common_conditions=common_conditions,
            recommendations=recommendations,
            refinement_options=refinement_options,
        )

    question = parsed.get("question") or fallback_question
    parsed_conditions = parsed.get("common_conditions")
    selected_ids = parsed.get("recommended_option_ids")
    if isinstance(parsed_conditions, list):
        common_conditions = [
            str(item) for item in parsed_conditions if str(item).strip()
        ] or common_conditions
    recommendations = _select_recommendations(refinement_options, selected_ids) or recommendations
    refinement_options = _trim_secondary_options(refinement_options, selected_ids)

    _emit(
        emitter,
        parsed.get(
            "reasoning",
            f"{effective_total} matches exceed the {candidate_limit}-parcel limit",
        ),
        {
            "stage": 2,
            "round": round_num,
            "returned_count": returned_count,
            "candidate_limit": candidate_limit,
            "total_matching": effective_total,
            "common_conditions": common_conditions,
            "recommendations": recommendations,
            "refinement_options": refinement_options,
        },
    )

    return GateResult(
        sufficient=False,
        question=question,
        common_conditions=common_conditions,
        recommendations=recommendations,
        refinement_options=refinement_options,
    )


def _fallback_common_conditions(
    refinement_options: list[dict[str, Any]], total_matching: int
) -> list[str]:
    """Build useful narrowing observations without an LLM."""
    conditions: list[str] = []
    sections = Counter(option["section"] for option in refinement_options if option.get("section"))
    if sections:
        section, count = sections.most_common(1)[0]
        conditions.append(f"LandWatch returned {count} narrowing options in {section.lower()}.")

    cheaper = [option["count"] for option in refinement_options if option.get("section") == "Price"]
    if cheaper:
        conditions.append(
            f"Price filters can reduce the search from {total_matching:,} matches to as few as {min(cheaper):,}."
        )
    locations = [option["count"] for option in refinement_options if option.get("section") in {"City", "County", "Region"}]
    if locations:
        conditions.append(
            f"Location filters can cut the result set down to between {min(locations):,} and {max(locations):,} matches."
        )
    return conditions or [f"LandWatch shows {total_matching:,} matching properties, so one more filter is needed."]


def _fallback_recommendations(refinement_options: list[dict[str, Any]]) -> list[str]:
    picks = refinement_options[:3]
    if not picks:
        return [
            "Add a tighter location, budget, acreage, or property type.",
        ]
    return [
        f"{option['section']}: {option['label']} ({option['count']:,} matches)"
        for option in picks
    ]


def _select_recommendations(
    refinement_options: list[dict[str, Any]],
    selected_ids: Any,
) -> list[str]:
    if not isinstance(selected_ids, list):
        return []
    by_id = {option["id"]: option for option in refinement_options}
    chosen: list[str] = []
    for raw_id in selected_ids:
        option = by_id.get(str(raw_id))
        if not option:
            continue
        chosen.append(
            f"{option['section']}: {option['label']} ({option['count']:,} matches)"
        )
    return chosen


def _strip_suffix(value: str, suffix: str) -> str:
    return value[: -len(suffix)] if value.endswith(suffix) else value


def _enum_value_from_option(spec_name: str, option: dict[str, Any]) -> str | None:
    spec = FILTER_CATALOG.get(spec_name)
    if not spec:
        return None
    option_id = option.get("id")
    label = slugify(str(option.get("label") or ""))
    for value in spec.values:
        if option_id not in (None, 0) and value.id == option_id:
            return value.value
        if slugify(value.label) == label or slugify(value.value) == label:
            return value.value
    return None


def _parse_range_value(value: str) -> tuple[float | None, float | None]:
    if value.startswith("under-"):
        return None, float(value.removeprefix("under-"))
    if value.startswith("over-"):
        return float(value.removeprefix("over-")), None
    low, _, high = value.partition("-")
    return float(low), float(high) if high else None


def _is_subset_range(
    current_min: float | int | None,
    current_max: float | int | None,
    new_min: float | int | None,
    new_max: float | int | None,
) -> bool:
    """Return True only when [new_min, new_max] is a proper subset of [current_min, current_max].

    A facet option that *removes* an existing bound always widens the search, so
    those cases are rejected immediately.  Boundary-touching ranges are also
    rejected: a new ceiling equal to an existing floor (or vice versa) yields an
    empty or degenerate intersection — not a meaningful narrowing.

    The logic covers six cases:
    1. No existing constraint   → any range is valid (nothing to narrow).
    2. new_min is None but current_min is set → floor would be dropped → widens.
    3. new_max is None but current_max is set → ceiling would be dropped → widens.
    4. new_min < current_min                  → floor would be lowered → widens.
    5. new_max > current_max                  → ceiling would be raised → widens.
    6. new_max <= current_min                 → ranges are disjoint or touch only at the boundary → empty.
    7. new_min >= current_max                 → same, opposite direction.
    """
    if current_min is None and current_max is None:
        return True

    # A proposed range that removes an existing bound always widens the search.
    if new_min is None and current_min is not None:
        return False
    if new_max is None and current_max is not None:
        return False

    if new_min is not None and current_min is not None and new_min < current_min:
        return False
    if new_max is not None and current_max is not None and new_max > current_max:
        return False

    # Proposed ceiling must be strictly above existing floor (else disjoint or degenerate).
    if current_min is not None and new_max is not None and new_max <= current_min:
        return False
    # Proposed floor must be strictly below existing ceiling (else disjoint or degenerate).
    if current_max is not None and new_min is not None and new_min >= current_max:
        return False

    return True


def _make_refinement_option(
    option_id: str,
    section: str,
    label: str,
    count: int,
    criteria_patch: dict[str, Any],
    clear_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": option_id,
        "section": section,
        "label": label,
        "count": count,
        "criteria_patch": criteria_patch,
        "clear_fields": clear_fields or [],
        "tier": "primary" if section in PRIMARY_FACET_SECTIONS else "secondary",
    }


def _trim_secondary_options(
    options: list[dict[str, Any]],
    selected_ids: Any,
) -> list[dict[str, Any]]:
    """Reduce clutter once the option set is wide, without ever hiding a
    primary facet (acreage, price, location, residence).

    Below `WIDE_RESULT_THRESHOLD` there is nothing to declutter, so every
    option is kept as-is. Above it, secondary/long-tail options (property
    type, activities, land use, geography, housing type, HOA) are trimmed to
    whichever the Stage 2 LLM call flagged as `recommended_option_ids` — the
    same IDs already used for the narrative `recommendations` text, so the
    dropdown and the prose never disagree about what is worth showing.
    """
    if len(options) <= WIDE_RESULT_THRESHOLD:
        return options

    primary = [o for o in options if o.get("tier") == "primary"]
    secondary = [o for o in options if o.get("tier") != "primary"]

    if isinstance(selected_ids, list) and selected_ids:
        wanted = {str(raw_id) for raw_id in selected_ids}
        picked = [o for o in secondary if o["id"] in wanted]
        if picked:
            secondary = picked

    return primary + secondary


def _build_refinement_options(
    criteria: dict[str, Any],
    facets: list[dict[str, Any]],
    total_matching: int,
) -> list[dict[str, Any]]:
    """Translate raw LandWatch facets into safe criteria patches."""
    options_by_section: dict[str, list[dict[str, Any]]] = {}

    for facet in facets:
        section = str(facet.get("section") or "").strip()
        if not section:
            continue
        built: list[dict[str, Any]] = []
        for raw_option in facet.get("options") or []:
            label = str(raw_option.get("label") or "").strip()
            count = raw_option.get("count")
            if not label or not isinstance(count, int) or count <= 0 or count >= total_matching:
                continue

            option_id = raw_option.get("id")
            slug = slugify(label)
            field_option_id = f"{slugify(section)}:{option_id if option_id not in (None, 0) else slug}"

            if section == "City" and criteria.get("city") != slug:
                built.append(
                    _make_refinement_option(
                        field_option_id,
                        section,
                        label,
                        count,
                        {"city": slug},
                    )
                )
            elif section == "County":
                county_slug = _strip_suffix(slug, "-county")
                if criteria.get("county") != county_slug:
                    built.append(
                        _make_refinement_option(
                            field_option_id,
                            section,
                            label,
                            count,
                            {"county": county_slug},
                        )
                    )
            elif section == "Region":
                region_slug = _strip_suffix(slug, "-region")
                if criteria.get("region") != region_slug:
                    built.append(
                        _make_refinement_option(
                            field_option_id,
                            section,
                            label,
                            count,
                            {"region": region_slug},
                        )
                    )
            elif section == "Residence" and criteria.get("has_residence") is None:
                if label in {"Yes", "No"}:
                    built.append(
                        _make_refinement_option(
                            field_option_id,
                            section,
                            label,
                            count,
                            {"has_residence": label == "Yes"},
                        )
                    )
            elif section == "Price":
                for preset in FILTER_CATALOG["price"].presets:
                    if preset.label != label:
                        continue
                    field_option_id = f"price:{preset.value}"
                    price_min, price_max = _parse_range_value(preset.value)
                    if not _is_subset_range(
                        criteria.get("price_min"),
                        criteria.get("price_max"),
                        price_min,
                        price_max,
                    ):
                        continue
                    built.append(
                        _make_refinement_option(
                            field_option_id,
                            section,
                            label,
                            count,
                            {"price_min": int(price_min) if price_min is not None else None, "price_max": int(price_max) if price_max is not None else None},
                            ["price_min", "price_max"],
                        )
                    )
                    break
            elif section == "Parcel Size":
                for preset in FILTER_CATALOG["acres"].presets:
                    if preset.label != label:
                        continue
                    field_option_id = f"parcel-size:{preset.value}"
                    acres_min, acres_max = _parse_range_value(preset.value)
                    if not _is_subset_range(
                        criteria.get("acres_min"),
                        criteria.get("acres_max"),
                        acres_min,
                        acres_max,
                    ):
                        continue
                    built.append(
                        _make_refinement_option(
                            field_option_id,
                            section,
                            label,
                            count,
                            {"acres_min": acres_min, "acres_max": acres_max},
                            ["acres_min", "acres_max"],
                        )
                    )
                    break
            else:
                section_map = {
                    "Property Types": "property_types",
                    "Activities": "activities",
                    "Geography": "geographies",
                    "Land Uses": "land_uses",
                    "Housing Type": "housing_types",
                    "HOA": "hoa",
                }
                spec_name = section_map.get(section)
                if not spec_name:
                    continue
                value = _enum_value_from_option(spec_name, raw_option)
                if value is None:
                    continue
                current_value = criteria.get(spec_name)
                if spec_name == "hoa":
                    if current_value == value:
                        continue
                    patch = {spec_name: value}
                else:
                    if spec_name != "property_types" and current_value not in (None, [], ""):
                        continue
                    if current_value == [value]:
                        continue
                    patch = {spec_name: [value]}
                built.append(
                    _make_refinement_option(
                        field_option_id,
                        section,
                        label,
                        count,
                        patch,
                    )
                )

        built.sort(key=lambda item: (item["count"], item["label"]))
        if built:
            # Primary facets (acreage, price, location, residence) are the
            # main way to narrow a search, so their range/bucket options —
            # e.g. every LandWatch price band — all get surfaced together
            # instead of being flattened down to two. Secondary facets stay
            # tightly capped; `_trim_secondary_options` decides which of
            # those survive once the overall set is wide.
            cap = 6 if section in PRIMARY_FACET_SECTIONS else 2
            options_by_section[section] = built[:cap]

    preferred_order = [
        "City",
        "County",
        "Region",
        "Price",
        "Parcel Size",
        "Property Types",
        "Residence",
        "Activities",
        "Geography",
        "Land Uses",
        "Housing Type",
        "HOA",
    ]
    combined: list[dict[str, Any]] = []
    for section in preferred_order:
        combined.extend(options_by_section.get(section, []))
    for section, values in options_by_section.items():
        if section not in preferred_order:
            combined.extend(values)
    return combined[:18]


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
