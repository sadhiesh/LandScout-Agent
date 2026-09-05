"""Supervisor Agent — primary orchestrator.

Port 8001. Parses intent, manages memory short-circuiting, and routes to
Scout, Enricher, and Scorer in sequence. The only agent that calls other agents.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
from typing import Any, Optional

from crewai import Agent
from fastapi import FastAPI
import uvicorn

from agents.common import (
    A2ACrewClient,
    ENRICHER_PORT,
    SCORER_PORT,
    SCOUT_PORT,
    SUPERVISOR_PORT,
    A2A_SCOUT_TIMEOUT,
    A2A_ENRICHER_TIMEOUT,
    A2A_SCORER_TIMEOUT,
    build_llm,
    create_trace_emitter,
    make_agent_url,
)
from agents.common.config import DISABLE_CRITERIA_CACHE
from agents.common.a2a_server import TaskRequest, TaskResponse
from agents.common.middleware import add_standard_cors, add_health_check
from agents.common.json_utils import extract_json
from agents.common.parcel_schema import normalize_listing
from agents.supervisor.criteria_gate import (
    apply_clarification_answer,
    assess_breadth,
    assess_criteria,
    assess_no_results,
    is_search_confirmation,
    is_search_rejection,
    merge_criteria,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def compute_criteria_fingerprint(criteria: dict[str, Any]) -> str:
    """Compute a stable fingerprint for criteria to detect changes.
    
    Args:
        criteria: Search criteria dict
        
    Returns:
        SHA256 hex digest of canonical JSON
    """
    canonical = json.dumps(criteria, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


CRITERIA_CONFIRMATION_KIND = "criteria_confirmation"

_CRITERIA_LABELS = {
    "state": "State",
    "county": "County",
    "city": "City",
    "region": "Region",
    "acres_min": "Minimum acres",
    "acres_max": "Maximum acres",
    "price_min": "Minimum price",
    "price_max": "Maximum price",
    "sqft_min": "Minimum house square feet",
    "sqft_max": "Maximum house square feet",
    "beds_min": "Minimum bedrooms",
    "baths_min": "Minimum bathrooms",
    "property_types": "Property types",
    "keyword": "Keyword",
    "activities": "Activities",
    "geographies": "Geographies",
    "land_uses": "Land uses",
    "housing_types": "Housing types",
    "has_residence": "Existing residence required",
    "owner_financing": "Owner financing required",
    "mineral_rights": "Mineral rights required",
    "hoa": "HOA",
}


def _format_criteria_value(field_name: str, value: Any) -> str:
    """Render one active criterion for the confirmation message."""
    if isinstance(value, list):
        return ", ".join(str(item).replace("-", " ").title() for item in value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field_name.startswith("price_") and isinstance(value, (int, float)):
        return f"${value:,.0f}"
    if isinstance(value, str):
        return value.replace("-", " ").title()
    return str(value)


def _criteria_confirmation_message(criteria: dict[str, Any]) -> str:
    """Build a complete deterministic summary before any search runs."""
    ordered_names = [
        *_CRITERIA_LABELS,
        *sorted(set(criteria) - set(_CRITERIA_LABELS)),
    ]
    lines = [
        f"- {_CRITERIA_LABELS.get(name, name.replace('_', ' ').title())}: "
        f"{_format_criteria_value(name, value)}"
        for name in ordered_names
        if (value := criteria.get(name)) not in (None, [], "")
    ]
    summary = "\n".join(lines) if lines else "- No active criteria"
    return (
        "Please confirm the complete search criteria:\n\n"
        f"{summary}\n\n"
        "Reply yes to run this search, or tell me what to change."
    )


def _has_active_criteria(criteria: dict[str, Any]) -> bool:
    """Whether at least one criterion has a value that Scout can act on."""
    return any(value not in (None, [], "") for value in criteria.values())


def _sanitize_criteria_for_scout(criteria: dict[str, Any]) -> dict[str, Any]:
    """Convert None to empty lists for list fields to match LandSearchInput validation.
    
    The LandWatch tool expects list fields (activities, geographies, land_uses, 
    housing_types, property_types) to be actual lists, not None. This conversion
    happens here rather than in the tool so the supervisor's internal representation
    can distinguish "not specified" (None) from "empty list specified" ([]).
    """
    sanitized = dict(criteria)
    list_fields = ["activities", "geographies", "land_uses", "housing_types", "property_types"]
    for field in list_fields:
        if sanitized.get(field) is None:
            sanitized[field] = []
    return sanitized


def create_supervisor_agent(provider: str | None = None, model: str | None = None) -> Agent:
    """Create the Supervisor agent with optional provider/model override."""
    llm = build_llm(provider=provider, model=model)
    
    agent = Agent(
        role="Land Investment Supervisor",
        goal=(
            "Orchestrate land parcel research by parsing user intent, managing "
            "session memory, and coordinating Scout, Enricher, and Scorer agents "
            "to produce a ranked shortlist with defensible rationales"
        ),
        backstory=(
            "You are the primary orchestrator for land investment research. "
            "You parse natural language requests into structured search criteria, "
            "check session memory to avoid redundant work, and delegate to "
            "specialized agents in sequence: Scout finds parcels, Enricher gathers "
            "facts, Scorer ranks and explains. You verify the final shortlist "
            "actually meets the user's stated criteria before returning it. You "
            "degrade gracefully when workers fail rather than aborting the run."
        ),
        tools=[],  # Supervisor delegates via A2A, doesn't call tools directly
        llm=llm,
        verbose=True,
        allow_delegation=False,  # Supervisor uses A2A, not CrewAI delegation
    )
    
    return agent


def _normalize_name(name: str) -> str:
    """Normalize a name for deterministic lookup."""
    # Strip common prefixes
    name = name.lower().strip()
    for prefix in ["my name is ", "i'm ", "i am ", "im "]:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    return name


def _parse_criteria_with_llm(
    user_message: str,
    run_id: str,
    emitter: Any,  # TraceEmitter
    current_criteria: Optional[dict[str, Any]] = None,
    current_results: Optional[list[dict[str, Any]]] = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """Parse criteria from user message using LLM with vocabulary validation.
    
    Args:
        user_message: Natural language request
        run_id: Run identifier for tracing
        emitter: Trace emitter for thought events
        
    Returns:
        Tuple of (criteria patch, provenance, turn resolution).
    """
    from tools.scoring import get_defaults
    from pathlib import Path
    
    # Start with defaults from criteria.yaml
    defaults = get_defaults()
    
    # Load the criteria parsing skill
    skill_path = Path(__file__).parent.parent.parent / "skills" / "criteria-parsing" / "SKILL.md"
    try:
        skill_content = skill_path.read_text()
        start_marker = "<!-- BEGIN turn_resolution -->"
        end_marker = "<!-- END turn_resolution -->"
        template_start = skill_content.find(start_marker)
        template_end = skill_content.find(end_marker)
        if template_start == -1 or template_end == -1:
            raise ValueError("Could not find prompt template in skill file")
        prompt_template = skill_content[
            template_start + len(start_marker):template_end
        ].strip()
    except Exception as e:
        logger.error(f"Failed to load criteria parsing skill: {e}", exc_info=True)
        fallback = {"state": defaults.get("state", "texas")}
        emitter.emit(
            "thought",
            "Criteria parsing skill unavailable; treating request as unspecified",
            {"error": str(e), "criteria": fallback},
        )
        return (
            fallback,
            {"state": "default"},
            {"intent": "search", "answer": None, "clear_fields": []},
        )
    
    # Replace {user_message} placeholder in template
    prompt = (
        prompt_template
        .replace('"{user_message}"', f'"{user_message}"')
        .replace(
            "{current_criteria_json}",
            json.dumps(current_criteria or {}, indent=2, default=str),
        )
        .replace(
            "{current_results_json}",
            json.dumps(current_results or [], indent=2, default=str),
        )
    )
    
    # Use the supervisor agent to parse
    agent = create_supervisor_agent(provider=provider, model=model)
    
    from crewai import Task, Crew
    
    task = Task(
        description=prompt,
        expected_output="JSON object with search criteria",
        agent=agent,
    )
    
    crew = Crew(agents=[agent], tasks=[task], verbose=False)
    
    try:
        result = crew.kickoff()
        parsed = extract_json(str(result))

        turn_resolution = {
            "intent": parsed.pop("_turn_intent", "search"),
            "answer": parsed.pop("_answer", None),
            "clear_fields": parsed.pop("_clear_fields", []),
        }
        valid_intents = {"search", "reset", "results_question", "off_topic", "conversational"}
        if turn_resolution["intent"] not in valid_intents:
            turn_resolution["intent"] = "search"
        if turn_resolution["intent"] == "results_question" and not current_results:
            turn_resolution = {"intent": "search", "answer": None, "clear_fields": []}
        
        # Which keys the model actually returned a value for, captured before
        # normalization writes defaults back into `parsed`. Without this, a
        # state filled in from config looks identical to one the model derived
        # from a city name, and the gate would offer to confirm a pure default.
        model_filled = {
            key
            for key, value in parsed.items()
            if value is not None and key != "_stated_fields"
        }
        
        # Validate and normalize
        from landwatch.models import SearchCriteria as LWCriteria
        from landwatch import places
        
        # Normalize state (texas -> TX or TX -> texas based on what LandWatch expects)
        # `or` rather than a get() default: the parser returns the key set to
        # null when the user named no state, and dict.get only falls back on a
        # missing key. Getting this wrong crashes the parse and drops the whole
        # run into the fallback path below.
        state_raw = parsed.get("state") or defaults.get("state", "texas")
        state_place = places.find_state(state_raw)
        if state_place:
            parsed["state"] = state_place.slug  # e.g., "texas"
        
        # Normalize county if present
        county_raw = parsed.get("county")
        if county_raw:
            # places.resolve returns a list
            county_places = places.resolve(county_raw, kind=places.PlaceKind.COUNTY, state=state_raw)
            if county_places:
                parsed["county"] = county_places[0].slug
        
        # Normalize city if present
        city_raw = parsed.get("city")
        if city_raw:
            # City resolution typically requires network call, but try offline first
            try:
                city_places = places.resolve(city_raw, kind=places.PlaceKind.CITY, state=state_raw)
                if city_places:
                    parsed["city"] = city_places[0].slug
            except Exception as e:
                logger.warning(f"[{run_id}] City resolution failed for '{city_raw}': {e}")
                # Keep the raw city name
                parsed["city"] = city_raw.lower()
        
        # Build provenance map - track which fields came from user
        all_fields = [
            "state", "county", "city", "region",
            "acres_min", "acres_max", "price_min", "price_max",
            "sqft_min", "sqft_max", "beds_min", "baths_min",
            "property_types", "keyword", "activities", "geographies",
            "land_uses", "housing_types", "has_residence",
            "owner_financing", "mineral_rights", "hoa"
        ]
        
        # The model reports which keys the user actually said. A value it
        # worked out itself (Texas, from "McKinney") is "inferred", not
        # "user" — the gate confirms inferences before searching, so
        # conflating the two would let assumptions through silently.
        #
        # If the model omits the list entirely, fall back to treating every
        # value as stated. Assuming the opposite would mark a whole request
        # inferred and trigger a confirming question on every single search.
        stated_raw = parsed.pop("_stated_fields", None)
        stated = set(stated_raw) if isinstance(stated_raw, list) else None
        
        provenance = {}
        for key in all_fields:
            if parsed.get(key) is not None:
                if key not in model_filled:
                    # Code wrote this, not the model — a config default.
                    provenance[key] = "default"
                elif stated is None or key in stated:
                    provenance[key] = "user"
                else:
                    provenance[key] = "inferred"
            else:
                provenance[key] = "default"
                # Only use defaults for critical missing fields (state, price_min, acres_min)
                # Let other fields remain null to give user maximum control
                if key in ["state"] and key in defaults:
                    parsed[key] = defaults.get(key)

        # On a follow-up amendment, an unstated default must not replace the
        # state already stored for the session.
        if (
            current_criteria
            and turn_resolution["intent"] == "search"
            and "state" not in model_filled
        ):
            parsed["state"] = None
        
        # Emit thought event with criteria and provenance
        emitter.emit(
            "thought",
            f"Parsed search criteria: {parsed.get('county') or 'any county'}, "
            f"{parsed.get('state') or 'TX'}",
            {
                "criteria": parsed,
                "provenance": provenance,
                "user_message": user_message[:100],
            }
        )
        
        logger.info(f"[{run_id}] Parsed criteria: {json.dumps(parsed)}")
        logger.info(f"[{run_id}] Provenance: {json.dumps(provenance)}")
        
        return parsed, provenance, turn_resolution
        
    except Exception as e:
        logger.error(f"[{run_id}] LLM criteria parsing failed: {e}", exc_info=True)
        # Return nothing but the state a search cannot be built without.
        # Returning the full `defaults` block here would hand the pipeline a
        # budget, an acreage range and three property types the user never
        # asked for, and mark them searchable — a failed parse would look
        # like a detailed request. With an empty result the gate asks instead.
        fallback = {"state": defaults.get("state", "texas")}
        emitter.emit(
            "thought",
            "Criteria parsing failed; treating the request as unspecified",
            {"error": str(e), "criteria": fallback},
        )
        return (
            fallback,
            {"state": "default"},
            {"intent": "search", "answer": None, "clear_fields": []},
        )


def _handle_identity_turn(
    session_id: str,
    user_message: str,
    pg: Any,  # PostgresStore
) -> dict[str, Any]:
    """Handle identity turn: resolve or create user, persist messages."""
    import uuid
    
    name = _normalize_name(user_message)
    name_key = name.lower().strip()
    
    # Look up by name_key
    user = pg.get_user_by_name_key(name_key)
    
    if user:
        # Returning user
        user_id = user["user_id"]
        display_name = user["display_name"]
        returning = True
        greeting = f"Welcome back, {display_name}!"
    else:
        # New user
        user_id = str(uuid.uuid4())
        display_name = name.title()
        pg.upsert_user(user_id, display_name, name_key)
        returning = False
        greeting = f"Hello, {display_name}! What kind of land are you looking for?"
    
    # Touch session with user_id
    pg.touch_session(session_id, user_id=user_id)
    
    # Persist the user turn; api/chat.py owns the final assistant message.
    pg.append_message(session_id, "user", user_message, run_id=None)
    
    return {
        "message": greeting,
        "user_id": user_id,
        "display_name": display_name,
        "returning": returning,
    }


def _load_pending_clarification(session_id: str) -> dict[str, Any]:
    """Recover the clarifying question the last turn left open, if any.

    The Supervisor stashes what it had parsed on the assistant message that
    asked the question, so the user's answer can be merged onto it rather than
    replacing it. Returns {} when the last turn was not a question.
    """
    from memory.store import PostgresStore

    try:
        with PostgresStore() as pg:
            messages = pg.get_messages(session_id)
    except Exception as e:
        logger.warning(f"Could not load prior clarification state: {e}")
        return {}

    # Scan back over the assistant's most recent turn, stopping at the user
    # message that preceded it. One turn can span several rows because the API
    # persists each journey step separately.
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        clarification = (message.get("payload") or {}).get("clarification")
        if clarification:
            return clarification

    return {}


def _load_session_context(session_id: str) -> dict[str, Any]:
    """Load criteria and scored results from the same latest summary message."""
    from memory.store import PostgresStore

    try:
        with PostgresStore() as pg:
            messages = pg.get_messages(session_id)
    except Exception as e:
        logger.warning(f"Could not load session context: {e}")
        return {"criteria": {}, "provenance": {}, "shortlist": []}

    for message in reversed(messages):
        payload = message.get("payload") or {}
        # Pending clarification/confirmation summaries intentionally contain
        # empty result arrays. Skip them so questions about the last completed
        # shortlist remain answerable while a new search is awaiting approval.
        if payload.get("awaiting_clarification") or payload.get("error"):
            continue
        if "criteria" not in payload:
            continue
        if "shortlist" not in payload and "candidates" not in payload:
            continue
        provenance = payload.get("criteria_provenance") or (
            (payload.get("clarification") or {}).get("pending_provenance")
        )
        # Return either shortlist (scored) or candidates (awaiting selection)
        # for results_question turn classification
        results = payload.get("shortlist") or payload.get("candidates") or []
        return {
            "criteria": dict(payload.get("criteria") or {}),
            "provenance": dict(provenance or {}),
            "shortlist": list(results),
        }
    return {"criteria": {}, "provenance": {}, "shortlist": []}


def _combine_cached_results(
    scores: list[dict[str, Any]],
    parcels: list[dict[str, Any]],
    limit: int,
    enrichments_by_id: Optional[dict[str, dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Rebuild canonical scored parcels from normalized and score rows."""
    scores_by_id = {str(row.get("parcel_id")): row for row in scores}
    combined: list[dict[str, Any]] = []
    for parcel in parcels:
        parcel_id = str(parcel.get("parcel_id"))
        score = scores_by_id.get(parcel_id)
        if not score:
            continue
        combined.append(
            {
                "property_id": parcel_id,
                "location": parcel.get("location") or {},
                "basic_info": parcel.get("basic_info") or {},
                "enrichment": (enrichments_by_id or {}).get(parcel_id, {}),
                "score": score.get("total_score", 0),
                "score_breakdown": {
                    "dimensions": score.get("dimension_scores") or {},
                    "highlights": score.get("highlights") or [],
                    "drawbacks": score.get("drawbacks") or [],
                    "not_assessed": score.get("not_assessed") or [],
                },
                "rationale": score.get("rationale") or "",
                "considerations": score.get("considerations") or [],
            }
        )
    combined.sort(key=lambda item: item.get("score", 0), reverse=True)
    return combined[:limit]


def _compact_result_context(shortlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep result Q&A grounded without sending full enrichment payloads."""
    compact: list[dict[str, Any]] = []
    for rank, parcel in enumerate(shortlist[:10], start=1):
        location = parcel.get("location") or {}
        info = parcel.get("basic_info") or {}
        compact.append(
            {
                "rank": rank,
                "property_id": parcel.get("property_id") or parcel.get("parcel_id"),
                "title": info.get("title"),
                "city": location.get("city"),
                "county": location.get("county"),
                "price": info.get("price"),
                "acres": info.get("acres"),
                "score": parcel.get("score") or parcel.get("total_score"),
                "rationale": parcel.get("rationale"),
                "highlights": (parcel.get("score_breakdown") or {}).get(
                    "highlights", []
                ),
                "drawbacks": (parcel.get("score_breakdown") or {}).get(
                    "drawbacks", []
                ),
            }
        )
    return compact


def _clarification_payload(
    criteria: dict[str, Any],
    provenance: dict[str, str],
    round_num: int,
    stage: int,
    gate: Any,  # GateResult
    original_run_id: str,
    candidate_run_id: str | None = None,
    kind: str = "criteria_clarification",
) -> dict[str, Any]:
    """Build the state a clarifying question needs to carry to the next turn.

    Returned to the API rather than written here: `api/chat.py` already
    persists `result["message"]` as an assistant message, so writing one from
    the Supervisor too would show the question to the user twice.
    """
    payload = {
        "kind": kind,
        "round": round_num + 1,
        "stage": stage,
        "pending_criteria": criteria,
        "pending_provenance": provenance,
        "missing": gate.missing,
        "confirmed_fields": gate.confirmed_fields,
        "relax_suggestion": gate.relax_suggestion,
        "original_run_id": original_run_id,  # NEW: For parent_run_id linking
    }
    if candidate_run_id:
        payload["candidate_run_id"] = candidate_run_id
    return payload


def _criteria_confirmation_payload(
    criteria: dict[str, Any],
    provenance: dict[str, str],
    round_num: int,
    original_run_id: str,
) -> dict[str, Any]:
    """Persist the exact criteria that an affirmative reply will execute."""
    return {
        "kind": CRITERIA_CONFIRMATION_KIND,
        "round": round_num,
        "stage": 1,
        "pending_criteria": criteria,
        "pending_provenance": provenance,
        "original_run_id": original_run_id,
    }


def _resolve_candidate_selection(
    session_id: str,
    candidate_run_id: str,
    selected_parcel_ids: list[str],
    candidate_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    """Load and validate a user's selection from a persisted Scout search."""
    from memory.store import PostgresStore

    if not selected_parcel_ids:
        return [], None, "Select at least one parcel to continue."
    if len(selected_parcel_ids) > candidate_limit:
        return (
            [],
            None,
            f"Select no more than {candidate_limit} parcels before continuing.",
        )

    with PostgresStore() as pg:
        search = pg.get_search(candidate_run_id)

    if not search or str(search.get("session_id")) != str(session_id):
        return [], None, "That candidate set is no longer available. Please run the search again."

    candidates = search.get("listings") or []
    by_id = {
        str(parcel.get("property_id")): parcel
        for parcel in candidates
        if parcel.get("property_id") is not None
    }
    unique_ids = list(dict.fromkeys(str(item) for item in selected_parcel_ids))
    unknown = [item for item in unique_ids if item not in by_id]
    if unknown:
        return (
            [],
            search,
            "One or more selected parcels are not part of the pending candidate set.",
        )

    return [by_id[item] for item in unique_ids], search, None


def orchestrate_pipeline(
    session_id: str,
    run_id: str,
    user_message: str,
    user_id: Optional[str] = None,
    skip_cache: bool = False,
    selected_parcel_ids: Optional[list[str]] = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """Orchestrate the full Scout → Enricher → Scorer pipeline.
    
    This is the main execution function called by the Supervisor agent.
    
    Args:
        session_id: Session identifier
        run_id: Run identifier
        user_message: User's natural language request
        user_id: Optional user ID (if already identified)
        selected_parcel_ids: Optional property IDs chosen from a pending search
        llm_provider: Optional LLM provider override
        llm_model: Optional LLM model override
        
    Returns:
        Dict with shortlist, criteria, execution metadata, and journey_steps
    """
    from memory.store import PostgresStore, RedisStore
    
    # Create trace emitter for supervisor (must be first, used throughout)
    from agents.common.trace import create_trace_emitter
    emitter = create_trace_emitter(run_id, "supervisor")
    
    # Emit LLM selection trace event
    from agents.common.model_catalog import resolve_selection
    selection = resolve_selection(llm_provider, llm_model)
    emitter.emit(
        "context",
        f"Using {selection.provider}/{selection.model}" + (" (reasoning)" if selection.reasoning else ""),
        {
            "provider": selection.provider,
            "model": selection.model,
            "reasoning": selection.reasoning,
        },
    )
    
    # Track journey steps for chat display
    journey_steps = []
    
    def add_step(step_type: str, message: str, details: dict = None):
        """Add a journey step that will become a chat message."""
        journey_steps.append({
            "type": step_type,
            "message": message,
            "details": details or {},
            "timestamp": dt.datetime.utcnow().isoformat(),
        })
    
    # Pipeline timing structure
    import time
    pipeline_timing = {
        "criteria_parse_ms": None,
        "scout_ms": None,
        "enricher_ms": None,
        "scorer_ms": None,
        "persistence_ms": None,
        "total_ms": None,
    }
    
    pipeline_start = time.time()
    
    # If the last turn was a clarifying question, this message is the answer to
    # it. Merge onto what was already known so a one-word reply does not wipe
    # out the county the user named earlier, then apply anything the reply
    # implies — accepting an assumption, or agreeing to drop a filter.
    session_context = _load_session_context(session_id)
    current_criteria = session_context["criteria"]
    current_provenance = session_context["provenance"]
    if current_criteria and not current_provenance:
        # Backward compatibility for messages written before provenance was
        # persisted. New turns preserve the exact map.
        current_provenance = {
            key: "user"
            for key, value in current_criteria.items()
            if value not in (None, [], "")
        }
    current_shortlist = session_context["shortlist"]
    pending = _load_pending_clarification(session_id)
    pending_kind = pending.get("kind")
    pending_criteria = pending.get("pending_criteria") or {}
    clarify_round = pending.get("round", 0)
    parent_run_id = pending.get("original_run_id") if pending else None
    selection_source_run_id = pending.get("candidate_run_id") if pending else None
    selected_parcel_ids = selected_parcel_ids or []
    selection_requested = bool(selected_parcel_ids)
    # Accept confirmation for both explicit criteria confirmation AND clarification responses
    confirmation_approved = (
        pending_kind in (CRITERIA_CONFIRMATION_KIND, "criteria_clarification")
        and _has_active_criteria(pending_criteria)
        and is_search_confirmation(user_message)
    )
    confirmation_cancelled = (
        pending_kind in (CRITERIA_CONFIRMATION_KIND, "criteria_clarification")
        and is_search_rejection(user_message)
    )
    turn_resolution: dict[str, Any] = {
        "intent": "selection" if selection_requested else "search",
        "answer": None,
        "clear_fields": [],
    }

    # A structured parcel selection already carries the exact pending criteria.
    # Re-parsing its generated chat label would spend an LLM call and could
    # accidentally alter the search the user selected from.
    if selection_requested and selection_source_run_id and pending.get("pending_criteria"):
        criteria = dict(pending["pending_criteria"])
        provenance = dict(pending.get("pending_provenance") or {})
        pipeline_timing["criteria_parse_ms"] = 0.0
        add_step(
            "selecting",
            f"✓ Using {len(selected_parcel_ids)} selected parcels",
            {"selected_parcel_ids": selected_parcel_ids},
        )
    elif confirmation_approved:
        criteria = dict(pending_criteria)
        provenance = dict(pending.get("pending_provenance") or {})
        for field_name, value in criteria.items():
            if value not in (None, [], "") and provenance.get(field_name) == "inferred":
                provenance[field_name] = "user"
        pipeline_timing["criteria_parse_ms"] = 0.0
        add_step(
            "confirmed",
            "✓ Search criteria confirmed",
            {"criteria": criteria},
        )
    elif confirmation_cancelled:
        criteria = dict(pending_criteria)
        provenance = dict(pending.get("pending_provenance") or {})
        turn_resolution["intent"] = "cancel"
        pipeline_timing["criteria_parse_ms"] = 0.0
    else:
        add_step("parsing", "🔍 Parsing your search criteria...")
        parse_start = time.time()
        parse_context_criteria = (
            pending.get("pending_criteria")
            if pending.get("pending_criteria")
            else current_criteria
        )
        criteria, provenance, turn_resolution = _parse_criteria_with_llm(
            user_message,
            run_id,
            emitter,
            current_criteria=parse_context_criteria,
            current_results=_compact_result_context(current_shortlist),
            provider=llm_provider,
            model=llm_model,
        )
        pipeline_timing["criteria_parse_ms"] = (time.time() - parse_start) * 1000
        logger.info(
            f"[{run_id}] Criteria parsed in "
            f"{pipeline_timing['criteria_parse_ms']:.0f}ms"
        )
    
    clear_fields = turn_resolution.get("clear_fields") or []
    if turn_resolution["intent"] == "reset":
        criteria = merge_criteria({}, criteria, clear_fields)
        pending = {}
        clarify_round = 0
        parent_run_id = None
    elif turn_resolution["intent"] in ("results_question", "off_topic", "conversational"):
        # These intents provide direct answers without modifying search state
        criteria = dict(current_criteria)
        provenance = dict(current_provenance)
    elif confirmation_approved:
        pending = {}
    elif confirmation_cancelled:
        pending = {}
    elif pending.get("pending_criteria") and not selection_requested:
        criteria = merge_criteria(
            pending["pending_criteria"],
            criteria,
            clear_fields,
        )
        provenance = {
            **(pending.get("pending_provenance") or {}),
            **{
                key: value
                for key, value in provenance.items()
                if value in {"user", "inferred"}
            },
        }
        criteria, provenance, notes = apply_clarification_answer(
            criteria, provenance, pending, user_message
        )
        emitter.emit(
            "memory_read",
            f"Merged answer with criteria from clarifying round {clarify_round}"
            + (f" ({'; '.join(notes)})" if notes else ""),
            {"round": clarify_round, "merged_criteria": criteria, "applied": notes},
        )
        for note in notes:
            add_step("assumed", f"✓ {note.capitalize()}")
    elif current_criteria and not selection_requested:
        criteria = merge_criteria(current_criteria, criteria, clear_fields)
        provenance = {
            **current_provenance,
            **{
                key: value
                for key, value in provenance.items()
                if value in {"user", "inferred"}
            },
        }
    else:
        criteria = merge_criteria({}, criteria, clear_fields)

    for field_name in clear_fields:
        if criteria.get(field_name) is None:
            provenance[field_name] = "cleared"
    
    # Build human-readable criteria summary
    criteria_summary = []
    if criteria.get("city"):
        criteria_summary.append(f"City: {criteria['city'].title()}")
    elif criteria.get("county"):
        criteria_summary.append(f"County: {criteria['county'].title()}")
    if criteria.get("state"):
        criteria_summary.append(f"State: {criteria['state'].title()}")
    if criteria.get("acres_min") or criteria.get("acres_max"):
        acres = f"{criteria.get('acres_min', 0)}-{criteria.get('acres_max', '∞')} acres"
        criteria_summary.append(f"Size: {acres}")
    if criteria.get("price_min") or criteria.get("price_max"):
        price_min = f"${criteria.get('price_min', 0):,}" if criteria.get("price_min") else "$0"
        price_max = f"${criteria.get('price_max'):,}" if criteria.get("price_max") else "∞"
        criteria_summary.append(f"Price: {price_min}-{price_max}")
    
    add_step("parsed", f"✓ Criteria parsed: {', '.join(criteria_summary)}", {"criteria": criteria})
    
    # Check memory for existing results with same criteria
    fingerprint = compute_criteria_fingerprint(criteria)
    
    with PostgresStore() as pg:
        # Identity check: if session has no user_id and no user_id provided,
        # treat this as a name turn
        session = pg.get_session(session_id)
        if not session:
            # Attach known user_id at create so the session appears in the sidebar
            pg.create_session(session_id, user_id=user_id)
            session = pg.get_session(session_id)
        
        session_user_id = session.get("user_id") if session else None
        
        if not session_user_id and not user_id:
            # This is an identity turn
            return _handle_identity_turn(session_id, user_message, pg)
        
        # Ensure we have a user_id
        effective_user_id = user_id or session_user_id
        
        # Title from first user message; always link orphan sessions to the user
        title = None
        if session and not session.get("title"):
            title = (
                user_message[:50] + "..."
                if len(user_message) > 50
                else user_message
            )
        pg.touch_session(
            session_id,
            user_id=effective_user_id if not session_user_id else None,
            title=title,
        )
        
        # Persist user message
        pg.append_message(session_id, "user", user_message, run_id=run_id)
        
        # Validate county support - only Collin County is currently implemented
        if criteria.get("county"):
            county_normalized = criteria["county"].lower().strip().replace(" county", "")
            if county_normalized not in ["collin"]:
                # Return early with helpful message
                assistant_msg = (
                    f"I can only search Collin County, Texas at this time. "
                    f"You requested {criteria['county'].title()} County, which is not yet supported. "
                    f"Would you like to search in Collin County instead, or expand your search to all of Texas?"
                )
                emitter.emit(
                    "thought",
                    f"County validation failed: {criteria['county']} not supported (only Collin)",
                    {"requested_county": criteria["county"], "supported_counties": ["collin"]}
                )
                emitter.close()
                
                return {
                    "message": assistant_msg,
                    "shortlist": [],
                    "criteria": criteria,
                    "criteria_provenance": provenance,
                    "error": "unsupported_county",
                    "journey_steps": journey_steps,
                }
        
        # Create run record FIRST - before Stage 1 gate - so trace events can
        # persist even for clarification rounds. This ensures continuity across
        # clarification exchanges.
        pg.create_run(run_id, session_id, criteria, fingerprint, parent_run_id)

        from tools.scoring import get_shortlist_size

        candidate_limit = get_shortlist_size()
        if confirmation_cancelled:
            from datetime import datetime

            pg.update_run_status(run_id, "completed", datetime.utcnow())
            emitter.emit(
                "thought",
                "User cancelled the pending search at criteria confirmation",
                {"cancelled_criteria": criteria},
            )
            emitter.close()
            return {
                "message": "Search canceled. Tell me whenever you want to revise or run it.",
                "shortlist": current_shortlist,
                "criteria": current_criteria,
                "criteria_provenance": current_provenance,
                "total_matching": len(current_shortlist),
                "journey_steps": journey_steps,
            }

        if turn_resolution["intent"] in ("results_question", "off_topic", "conversational"):
            from datetime import datetime

            # Generate appropriate answer and step message based on intent
            if turn_resolution["intent"] == "results_question":
                answer = turn_resolution.get("answer") or (
                    "I could not answer that from the saved parcel results. "
                    "Please ask about a specific parcel or score."
                )
                step_msg = "✓ Answered from the saved scored results"
                step_data = {"result_count": len(current_shortlist)}
                emitter.memory_read(
                    "scored_result_context",
                    f"answered from {len(current_shortlist)} saved parcels",
                )
            elif turn_resolution["intent"] == "off_topic":
                answer = turn_resolution.get("answer") or (
                    "I specialize in land and property searches. I can help you find "
                    "parcels by location, price, acreage, or property type. What kind "
                    "of land are you looking for?"
                )
                step_msg = "💬 Redirected off-topic question to land search"
                step_data = {}
            else:  # conversational
                answer = turn_resolution.get("answer") or (
                    "I help you find land parcels by searching LandWatch based on your "
                    "criteria (location, price, acreage, type), then enriching and scoring "
                    "the results. Tell me what you're looking for!"
                )
                step_msg = "💬 Answered system question"
                step_data = {}

            add_step("conversational", step_msg, step_data)
            pg.update_run_status(run_id, "completed", datetime.utcnow())
            emitter.close()
            return {
                "message": answer,
                "shortlist": current_shortlist,
                "criteria": criteria,
                "criteria_provenance": provenance,
                "total_matching": len(current_shortlist),
                "answered_from_memory": True,
                "journey_steps": journey_steps,
            }

        if selection_requested and not selection_source_run_id:
            from datetime import datetime

            pg.update_run_status(run_id, "awaiting_clarification", datetime.utcnow())
            emitter.close()
            return {
                "message": "There is no pending candidate set to select from. Please run the search again.",
                "shortlist": [],
                "criteria": criteria,
                "criteria_provenance": provenance,
                "awaiting_clarification": True,
                "journey_steps": journey_steps,
            }
        
        # Stage 1 of the sufficiency gate. Blocks only when nothing actionable
        # was given; anything searchable goes through and is judged by Stage 2
        # against the real match count.
        gate = None
        if not selection_requested and not confirmation_approved:
            from functools import partial
            from agents.supervisor.criteria_gate import _default_llm as _gate_llm
            
            gate = assess_criteria(
                criteria=criteria,
                provenance=provenance,
                user_message=user_message,
                round_num=clarify_round,
                emitter=emitter,
                llm_fn=partial(_gate_llm, provider=llm_provider, model=llm_model),
                # The mandatory full-criteria confirmation below also confirms
                # inferred locations, avoiding two consecutive confirmation
                # questions for the same search.
                confirm_inferred_locations=False,
            )
        
        if gate is not None and not gate.sufficient:
            add_step("clarifying", "💬 Need a bit more to go on")
            
            # Mark run as awaiting clarification
            from datetime import datetime
            pg.update_run_status(run_id, "awaiting_clarification", datetime.utcnow())
            
            emitter.close()
            
            return {
                "message": gate.question,
                "shortlist": [],
                "criteria": criteria,
                "criteria_provenance": provenance,
                "awaiting_clarification": True,
                "clarification": _clarification_payload(
                    criteria, provenance, clarify_round, 1, gate, run_id
                ),
                "journey_steps": journey_steps,
            }
        
        if gate is not None and gate.assumptions:
            add_step(
                "assumed",
                f"✓ Proceeding with assumed {', '.join(gate.assumptions)}",
                {"assumptions": gate.assumptions},
            )

        if (
            not selection_requested
            and not confirmation_approved
            and turn_resolution["intent"] in {"search", "reset"}
        ):
            from datetime import datetime

            if not _has_active_criteria(criteria):
                pg.update_run_status(
                    run_id,
                    "awaiting_clarification",
                    datetime.utcnow(),
                )
                emitter.emit(
                    "thought",
                    "No active criteria available for confirmation",
                    {"criteria": criteria},
                )
                emitter.close()
                return {
                    "message": (
                        "I do not have an active search criterion to confirm. "
                        "What location, acreage, budget, or property type should I use?"
                    ),
                    "shortlist": [],
                    "criteria": criteria,
                    "criteria_provenance": provenance,
                    "awaiting_clarification": True,
                    "journey_steps": journey_steps,
                }

            add_step(
                "confirming",
                "Reviewing the complete criteria before search",
                {"criteria": criteria},
            )
            pg.update_run_status(
                run_id,
                "awaiting_clarification",
                datetime.utcnow(),
            )
            emitter.emit(
                "thought",
                "Waiting for explicit criteria confirmation before Scout",
                {"criteria": criteria},
            )
            emitter.close()
            return {
                "message": _criteria_confirmation_message(criteria),
                "shortlist": [],
                "criteria": criteria,
                "criteria_provenance": provenance,
                "awaiting_clarification": True,
                "clarification": _criteria_confirmation_payload(
                    criteria,
                    provenance,
                    clarify_round,
                    run_id,
                ),
                "journey_steps": journey_steps,
            }
        
        # Check cache disable flags
        if selection_requested:
            logger.info(f"[{run_id}] Cache bypassed for explicit parcel selection")
            emitter.memory_read("criteria_cache_check", "bypassed - parcel selection")
        elif skip_cache:
            logger.info(f"[{run_id}] Cache deliberately bypassed via skip_cache flag")
            emitter.memory_read("criteria_cache_check", "bypassed - skip_cache=true")
        elif DISABLE_CRITERIA_CACHE:
            logger.info(f"[{run_id}] Cache disabled globally via DISABLE_CRITERIA_CACHE")
            emitter.memory_read("criteria_cache_check", "bypassed - global disable")
        # Check if we have a cached run with this fingerprint
        elif session and session.get("last_criteria_fingerprint") == fingerprint:
            last_run_id = session.get("last_run_id")
            if last_run_id:
                logger.info(
                    f"[{run_id}] Criteria fingerprint matches last run {last_run_id}, "
                    "returning cached results"
                )
                
                # Emit memory_read event for cache hit
                emitter.memory_read("criteria_cache_check", "hit - returning cached shortlist")
                
                # Fetch cached scores
                scores = pg.get_scores_by_run(last_run_id)
                parcels = pg.get_parcels_by_run(last_run_id)
                
                if scores and parcels:
                    enrichments_by_id = {}
                    for parcel in parcels:
                        parcel_id = str(parcel.get("parcel_id"))
                        enrichments_by_id[parcel_id] = {
                            row["source"]: row.get("data")
                            for row in pg.get_enrichments_by_parcel(
                                last_run_id, parcel_id
                            )
                        }
                    cached_shortlist = _combine_cached_results(
                        scores,
                        parcels,
                        candidate_limit,
                        enrichments_by_id=enrichments_by_id,
                    )
                    cached_search = pg.get_search(last_run_id) or {}
                    assistant_msg = (
                        f"Here are the top {len(cached_shortlist)} properties "
                        "(from cache)."
                    )
                    from datetime import datetime

                    pg.update_run_status(run_id, "completed", datetime.utcnow())
                    emitter.close()
                    return {
                        "message": assistant_msg,
                        "shortlist": cached_shortlist,
                        "criteria": criteria,
                        "criteria_provenance": provenance,
                        "total_matching": cached_search.get(
                            "total_matching", len(cached_shortlist)
                        ),
                        "cached": True,
                        "original_run_id": last_run_id,
                    }
        else:
            # Emit memory_read event for cache miss
            emitter.memory_read("criteria_cache_check", "miss - will run pipeline")
    
    # Execute pipeline via A2A
    def trace_callback(kind: str, summary: str, data: dict | None) -> None:
        """Trace callback that uses the emitter."""
        emitter.emit(kind, summary, data)
    
    a2a_client = A2ACrewClient("supervisor", trace_callback=trace_callback)
    
    try:
        scout_start = time.time()
        if selection_requested:
            parcels, source_search, selection_error = _resolve_candidate_selection(
                session_id=session_id,
                candidate_run_id=selection_source_run_id,
                selected_parcel_ids=selected_parcel_ids,
                candidate_limit=candidate_limit,
            )
            if selection_error:
                from datetime import datetime

                with PostgresStore() as pg:
                    pg.update_run_status(
                        run_id, "awaiting_clarification", datetime.utcnow()
                    )
                emitter.close()
                return {
                    "message": selection_error,
                    "shortlist": [],
                    "candidates": (source_search or {}).get("listings", []),
                    "criteria": criteria,
                    "criteria_provenance": provenance,
                    "total_matching": (source_search or {}).get("total_matching", 0),
                    "awaiting_clarification": True,
                    "clarification": pending,
                    "journey_steps": journey_steps,
                }

            raw_listings = parcels
            search_url = source_search.get("search_url", "")
            total_matching = source_search.get("total_matching", len(parcels))
            scout_error = None
            normalization_errors = []
            logger.info(
                f"[{run_id}] Reusing {len(parcels)} selected parcels from "
                f"search {selection_source_run_id}"
            )
            add_step(
                "selected",
                f"✓ Selected {len(parcels)} parcels for full analysis",
                {"selected_parcel_ids": selected_parcel_ids},
            )
        else:
            # Step 1: Scout - search for parcels
            logger.info(f"[{run_id}] Delegating to Scout...")

            # Sanitize criteria for Scout's tool: convert None to [] for list fields
            scout_criteria = _sanitize_criteria_for_scout(criteria)
            scout_context = {"criteria": scout_criteria, "run_id": run_id}
            estimated_tokens = len(json.dumps(scout_context)) // 4
            emitter.context(scout_context, estimated_tokens)

            scout_response = a2a_client.send_task(
                target_url=make_agent_url(SCOUT_PORT),
                run_id=run_id,
                task_description=(
                    f"Search for land parcels matching these criteria: {json.dumps(scout_criteria)}. "
                    "Use the landwatch_search tool and return its output EXACTLY as-is. "
                    "Do not rename fields - preserve 'listings', 'search_url', "
                    "'total_matching', 'returned'."
                ),
                expected_output=(
                    "JSON with 'listings' array (not 'parcels'), search_url, "
                    "total_matching, returned"
                ),
                context={
                    "criteria": criteria,
                    "run_id": run_id,
                    "llm_provider": llm_provider,
                    "llm_model": llm_model,
                },
                timeout=A2A_SCOUT_TIMEOUT,
            )

            scout_data = extract_json(scout_response)
            # Accept the legacy alias defensively; Scout's contract is listings.
            raw_listings = scout_data.get("parcels") or scout_data.get("listings", [])
            search_url = scout_data.get("search_url") or scout_data.get("url", "")
            total_matching = scout_data.get("total_matching", 0)
            scout_error = scout_data.get("error")

            logger.info(
                f"[{run_id}] Scout response: total_matching={total_matching}, "
                f"raw_listings_count={len(raw_listings)}, "
                f"error={scout_error}, "
                f"search_url={search_url[:100] if search_url else 'N/A'}"
            )

            parcels = []
            normalization_errors = []
            for idx, listing in enumerate(raw_listings):
                try:
                    parcels.append(normalize_listing(listing))
                except Exception as e:
                    normalization_errors.append(
                        f"Listing {idx}: {type(e).__name__}: {e}"
                    )
                    logger.error(
                        f"[{run_id}] Failed to normalize listing {idx}: {e}",
                        exc_info=True,
                    )

            if normalization_errors:
                logger.warning(
                    f"[{run_id}] Normalization errors: {normalization_errors}"
                )
        
        pipeline_timing["scout_ms"] = (time.time() - scout_start) * 1000
        logger.info(f"[{run_id}] Scout completed in {pipeline_timing['scout_ms']:.0f}ms - {len(parcels)} parcels")
        
        # Detect Scout/tool failures separately from honest zero-match searches.
        if scout_error and len(parcels) == 0:
            diagnostic_msg = "⚠️ Scout could not complete the parcel search"

            if search_url:
                diagnostic_msg += f" — Search URL: {search_url}"
            diagnostic_msg += f" — Error: {scout_error}"

            add_step(
                "retrieval_failed",
                diagnostic_msg,
                {
                    "total_matching": total_matching,
                    "returned": 0,
                    "raw_listings_count": len(raw_listings),
                    "normalization_errors": normalization_errors[:3] if normalization_errors else None,
                    "search_url": search_url,
                    "error": scout_error,
                    "suggestion": "Try again in a few moments or refine your search criteria",
                },
            )
        # Detect retrieval failure - found matches but got 0 results
        elif total_matching > 0 and len(parcels) == 0:
            # Critical diagnostic: LandWatch found properties but we couldn't retrieve them
            diagnostic_msg = f"⚠️ Found {total_matching} matching properties but couldn't retrieve listing details"
            
            # Determine the likely cause
            if scout_error:
                diagnostic_msg += f" — Error: {scout_error}"
            elif normalization_errors:
                diagnostic_msg += f" — Normalization failed for all {len(raw_listings)} listings"
            elif len(raw_listings) == 0:
                diagnostic_msg += " — LandWatch returned 0 listing details (likely rate limiting or network issue)"
            else:
                diagnostic_msg += " — Unknown parsing or processing error"
            
            add_step("retrieval_failed", diagnostic_msg, {
                "total_matching": total_matching,
                "returned": 0,
                "raw_listings_count": len(raw_listings),
                "normalization_errors": normalization_errors[:3] if normalization_errors else None,
                "search_url": search_url,
                "error": scout_error,
                "suggestion": "Try narrowing your search criteria or try again in a few moments"
            })
        else:
            add_step("searched", f"✓ Found {total_matching} matching properties ({len(parcels)} retrieved)", {
                "total_matching": total_matching,
                "returned": len(parcels),
                "search_url": search_url
            })
        
        # Write searches row immediately after Scout returns
        with PostgresStore() as pg:
            pg.insert_search(
                run_id=run_id,
                session_id=session_id,
                criteria=criteria,
                search_url=search_url,
                total_matching=total_matching,
                returned=len(parcels),
                listings=parcels,
            )
        
        if not parcels:
            # Distinguish between "no matches" and "retrieval failure"
            if scout_error:
                assistant_msg = (
                    "The Scout search failed before parcel details could be processed. "
                    f"Error: {scout_error}"
                )
                if search_url:
                    assistant_msg += f"\n\nSearch URL: {search_url}"
                add_step(
                    "complete",
                    "✗ Scout failed",
                    {
                        "total_matching": total_matching,
                        "search_url": search_url,
                        "error": scout_error,
                    },
                )
            elif total_matching > 0:
                assistant_msg = (
                    f"Found {total_matching} properties that match your criteria, but couldn't retrieve "
                    f"listing details. This may be due to rate limiting or temporary network issues. "
                    f"Please try again in a few moments or refine your search criteria."
                )
                if search_url:
                    assistant_msg += f"\n\nSearch URL: {search_url}"
                add_step("complete", f"✗ Retrieval failed ({total_matching} found, 0 retrieved)", {
                    "total_matching": total_matching,
                    "search_url": search_url
                })
            else:
                # Nothing matched. Rather than dead-ending, name the filter
                # most likely to blame and offer to drop it — narrowing is the
                # wrong direction when the result set is already empty.
                relax = assess_no_results(
                    criteria=criteria,
                    round_num=clarify_round,
                    emitter=emitter,
                )
                
                if not relax.sufficient:
                    add_step(
                        "clarifying",
                        f"💬 No matches; offering to drop the "
                        f"{relax.relax_suggestion['label']} filter",
                        {"relax": relax.relax_suggestion},
                    )
                    
                    from datetime import datetime
                    
                    with PostgresStore() as pg:
                        pg.update_run_status(run_id, "completed", datetime.utcnow())
                    
                    emitter.close()
                    
                    return {
                        "message": relax.question,
                        "shortlist": [],
                        "criteria": criteria,
                        "criteria_provenance": provenance,
                        "total_matching": 0,
                        "awaiting_clarification": True,
                        "clarification": _clarification_payload(
                            criteria,
                            provenance,
                            clarify_round,
                            2,
                            relax,
                            run_id,
                            kind="criteria_relaxation",
                        ),
                        "journey_steps": journey_steps,
                    }
                
                assistant_msg = "No parcels found matching your criteria."
                add_step("complete", "✗ No parcels found", {"total_matching": 0})

            from datetime import datetime

            with PostgresStore() as pg:
                pg.update_run_status(run_id, "completed", datetime.utcnow())

            return {
                "message": assistant_msg,
                "shortlist": [],
                "criteria": criteria,
                "criteria_provenance": provenance,
                "journey_steps": journey_steps,
            }
        
        # Stage 2 is a hard guard on the records Scout actually returned.
        # More than the shortlist size never reaches Enricher or Scorer.
        breadth = assess_breadth(
            criteria=criteria,
            parcels=parcels,
            candidate_limit=candidate_limit,
            total_matching=total_matching,
            provenance=provenance,
            round_num=clarify_round,
            emitter=emitter,
        )
        
        if not breadth.sufficient:
            add_step(
                "clarifying",
                f"💬 Select up to {candidate_limit} of {len(parcels)} returned parcels",
                {
                    "returned_count": len(parcels),
                    "candidate_limit": candidate_limit,
                    "total_matching": total_matching,
                },
            )
            
            # The search itself completed, so this is not a failed run. The
            # session's last-run pointer is deliberately left alone: priming
            # the fingerprint cache with a run that has no scores would make
            # an identical follow-up look like a cache hit.
            with PostgresStore() as pg:
                from datetime import datetime
                
                pg.update_run_status(run_id, "completed", datetime.utcnow())
            
            emitter.close()
            
            return {
                "message": breadth.question,
                "shortlist": [],
                "candidates": parcels,
                "candidate_analysis": {
                    "common_conditions": breadth.common_conditions,
                    "recommendations": breadth.recommendations,
                },
                "candidate_limit": candidate_limit,
                "criteria": criteria,
                "criteria_provenance": provenance,
                "total_matching": total_matching,
                "awaiting_clarification": True,
                "clarification": _clarification_payload(
                    criteria,
                    provenance,
                    clarify_round,
                    2,
                    breadth,
                    run_id,
                    candidate_run_id=run_id,
                    kind="candidate_selection",
                ),
                "journey_steps": journey_steps,
            }
        
        # Step 2: Enricher - gather additional facts
        enricher_start = time.time()
        logger.info(f"[{run_id}] Delegating to Enricher...")
        add_step("enriching", f"📊 Gathering additional data for {len(parcels)} properties...")
        
        # Emit context event for Enricher delegation
        enricher_context = {"parcels": parcels, "run_id": run_id}
        estimated_tokens = len(json.dumps(enricher_context)) // 4
        emitter.context(enricher_context, estimated_tokens)
        
        try:
            enricher_response = a2a_client.send_task(
                target_url=make_agent_url(ENRICHER_PORT),
                run_id=run_id,
                task_description=(
                    f"Enrich these {len(parcels)} parcels with landwatch_detail and county_comps: "
                    f"{json.dumps(parcels[:5])}... "  # Send sample for context
                    "Run all enabled enrichers and track sources_used and sources_failed."
                ),
                expected_output="JSON with enriched parcels, sources_used, sources_failed",
                context={
                    "parcels": parcels,
                    "run_id": run_id,
                    "llm_provider": llm_provider,
                    "llm_model": llm_model,
                },
                timeout=A2A_ENRICHER_TIMEOUT,
            )
            
            enriched_data = extract_json(enricher_response)
            enriched_parcels = enriched_data.get("enriched_parcels", parcels)
            sources_used = enriched_data.get("sources_used", [])
            sources_failed = enriched_data.get("sources_failed", [])
        except TimeoutError as e:
            logger.error(f"[{run_id}] Enricher timed out: {e}", exc_info=True)
            emitter.emit(
                "error",
                f"✗ Enricher timed out after {A2A_ENRICHER_TIMEOUT}s",
                {"error": str(e), "timeout_seconds": A2A_ENRICHER_TIMEOUT, "parcel_count": len(parcels)},
            )
            # Continue without enrichment rather than failing the entire run
            enriched_parcels = parcels
            sources_used = []
            sources_failed = ["All enrichers timed out"]
        except RuntimeError as e:
            logger.error(f"[{run_id}] Enricher failed: {e}", exc_info=True)
            emitter.emit(
                "error",
                f"✗ Enricher failed: {str(e)[:100]}",
                {"error": str(e)},
            )
            # Continue without enrichment
            enriched_parcels = parcels
            sources_used = []
            sources_failed = [f"Enricher error: {str(e)[:100]}"]
        
        pipeline_timing["enricher_ms"] = (time.time() - enricher_start) * 1000
        logger.info(
            f"[{run_id}] Enricher completed in {pipeline_timing['enricher_ms']:.0f}ms - "
            f"{len(sources_used)} sources used, {len(sources_failed)} failed"
        )
        add_step("enriched", f"✓ Enriched with {len(sources_used)} data sources", {
            "sources_used": sources_used,
            "sources_failed": sources_failed
        })
        
        # Step 3: Scorer - rank and generate rationales
        scorer_start = time.time()
        logger.info(f"[{run_id}] Delegating to Scorer...")
        add_step("scoring", f"⚖️ Scoring and ranking {len(enriched_parcels)} properties...")
        
        # Emit context event for Scorer delegation
        scorer_context = {"enriched_parcels": enriched_parcels, "criteria": criteria, "run_id": run_id}
        estimated_tokens = len(json.dumps(scorer_context)) // 4
        emitter.context(scorer_context, estimated_tokens)
        
        try:
            scorer_response = a2a_client.send_task(
                target_url=make_agent_url(SCORER_PORT),
                run_id=run_id,
                task_description=(
                    f"Score these {len(enriched_parcels)} enriched parcels against criteria: "
                    f"{json.dumps(criteria)}. Use deterministic scoring from tools/scoring, "
                    "then write rationales based on the score breakdowns. "
                    f"Return the top {candidate_limit}."
                ),
                expected_output="JSON with scored parcels sorted by score descending",
                context={
                    "enriched_parcels": enriched_parcels,
                    "criteria": criteria,
                    "run_id": run_id,
                    "llm_provider": llm_provider,
                    "llm_model": llm_model,
                },
                timeout=A2A_SCORER_TIMEOUT,
            )
            
            scored_data = extract_json(scorer_response)
            scored_parcels = scored_data.get("scored_parcels", [])
        except TimeoutError as e:
            logger.error(f"[{run_id}] Scorer timed out: {e}", exc_info=True)
            emitter.emit(
                "error",
                f"✗ Scorer timed out after {A2A_SCORER_TIMEOUT}s",
                {"error": str(e), "timeout_seconds": A2A_SCORER_TIMEOUT, "parcel_count": len(enriched_parcels)},
            )
            emitter.close()
            
            from datetime import datetime
            with PostgresStore() as pg:
                pg.update_run_status(run_id, "failed", datetime.utcnow())
            
            return {
                "message": "Scoring is taking longer than expected. The parcels may be too complex or the system is under heavy load. Please try again later.",
                "shortlist": [],
                "journey_steps": journey_steps,
            }
        except RuntimeError as e:
            logger.error(f"[{run_id}] Scorer failed: {e}", exc_info=True)
            emitter.emit(
                "error",
                f"✗ Scorer failed: {str(e)[:100]}",
                {"error": str(e)},
            )
            emitter.close()
            
            from datetime import datetime
            with PostgresStore() as pg:
                pg.update_run_status(run_id, "failed", datetime.utcnow())
            
            return {
                "message": f"Scoring failed: {str(e)}",
                "shortlist": [],
                "journey_steps": journey_steps,
            }
        
        pipeline_timing["scorer_ms"] = (time.time() - scorer_start) * 1000
        logger.info(f"[{run_id}] Scorer completed in {pipeline_timing['scorer_ms']:.0f}ms - {len(scored_parcels)} parcels scored")
        add_step("scored", f"✓ Scored and ranked all properties", {
            "count": len(scored_parcels)
        })
        
        # Take top N for shortlist
        from tools.scoring import get_shortlist_size
        
        shortlist_size = get_shortlist_size()
        shortlist = scored_parcels[:shortlist_size]
        
        add_step("complete", f"✓ Analysis complete! Showing top {len(shortlist)} of {total_matching} properties", {
            "shortlist_size": len(shortlist),
            "total_matching": total_matching
        })
        
        # Emit thought event for shortlist cut
        emitter.emit(
            "thought",
            f"Selected top {len(shortlist)} of {len(scored_parcels)} parcels for shortlist",
            {"shortlist_size": shortlist_size, "total_scored": len(scored_parcels)}
        )
        
        # Store results in memory
        persist_start = time.time()
        with PostgresStore() as pg:
            # Store parcels
            for parcel in scored_parcels:
                pg.insert_parcel(
                    parcel_id=str(parcel.get("property_id")),
                    run_id=run_id,
                    source="landwatch",
                    source_id=str(parcel.get("property_id")),
                    location=parcel.get("location", {}),
                    basic_info=parcel.get("basic_info", {}),
                )
                
                # Store enrichments
                for source, data in parcel.get("enrichment", {}).items():
                    if data:
                        pg.insert_enrichment(
                            parcel_id=str(parcel.get("property_id")),
                            run_id=run_id,
                            source=source,
                            data=data,
                        )
                
                # Store score
                score_breakdown = parcel.get("score_breakdown", {})
                pg.insert_score(
                    parcel_id=str(parcel.get("property_id")),
                    run_id=run_id,
                    total_score=parcel.get("score", 0),
                    dimension_scores=score_breakdown.get("dimensions", {}),
                    rationale=parcel.get("rationale", ""),
                    highlights=score_breakdown.get("highlights", []),
                    drawbacks=score_breakdown.get("drawbacks", []),
                    not_assessed=score_breakdown.get("not_assessed", []),
                    considerations=parcel.get("considerations", []),
                )
            
            # Emit memory_write event
            emitter.memory_write("parcels_scores_enrichments", len(scored_parcels))
            
            # Update run status
            from datetime import datetime
            
            pg.update_run_status(run_id, "completed", datetime.utcnow())
            
            # A selected subset does not represent every parcel matching the
            # broad criteria, so it must not prime that criteria's cache.
            if not selection_requested:
                pg.update_session_last_run(session_id, run_id, fingerprint)
        
        pipeline_timing["persistence_ms"] = (time.time() - persist_start) * 1000
        pipeline_timing["total_ms"] = (time.time() - pipeline_start) * 1000
        
        # Log performance summary
        logger.info(
            f"[{run_id}] Pipeline total: {pipeline_timing['total_ms']:.0f}ms "
            f"(parse={pipeline_timing['criteria_parse_ms']:.0f}ms, "
            f"scout={pipeline_timing['scout_ms']:.0f}ms, "
            f"enrich={pipeline_timing['enricher_ms']:.0f}ms, "
            f"score={pipeline_timing['scorer_ms']:.0f}ms, "
            f"persist={pipeline_timing['persistence_ms']:.0f}ms)"
        )
        
        # Emit comprehensive timing event
        emitter.emit(
            "pipeline_timing",
            f"Pipeline: {pipeline_timing['total_ms']/1000:.1f}s total",
            pipeline_timing
        )
        
        assistant_msg = f"Found {total_matching} properties, showing top {len(shortlist)}."
        return {
            "message": assistant_msg,
            "shortlist": shortlist,
            "criteria": criteria,
            "criteria_provenance": provenance,
            "sources_used": sources_used,
            "sources_failed": sources_failed,
            "total_found": len(scored_parcels),
            "total_matching": total_matching,
            "journey_steps": journey_steps,
        }
        
    except Exception as e:
        logger.error(f"[{run_id}] Pipeline failed: {e}", exc_info=True)
        logger.error(f"[{run_id}] Exception type: {type(e).__name__}")
        logger.error(f"[{run_id}] Exception details: {str(e)}")
        
        # Emit error event
        emitter.error("Pipeline failed", str(e))
        
        # Store failed run
        with PostgresStore() as pg:
            from datetime import datetime
            
            pg.update_run_status(run_id, "failed", datetime.utcnow())
        
        # Close emitter
        emitter.close()
        
        return {
            "message": f"Pipeline failed: {e}",
            "shortlist": [],
            "criteria": criteria if 'criteria' in locals() else {},
            "error": str(e),
            "journey_steps": journey_steps if 'journey_steps' in locals() else [],
        }
    
    # Close emitter on success
    emitter.close()


def main() -> None:
    """Run the Supervisor agent as an A2A server."""
    logger.info("Starting Supervisor agent...")

    # Module-level TaskRequest/TaskResponse (imported above) — required with
    # from __future__ import annotations. Nested models inside main() are
    # unresolved by FastAPI and become query params → 422 on JSON body posts.
    app = FastAPI(title="Supervisor A2A Service")
    
    # Add standard middleware and health check
    add_standard_cors(app)
    add_health_check(app, "supervisor")
    
    @app.post("/message", response_model=TaskResponse)
    async def handle_message(task_request: TaskRequest) -> TaskResponse:
        """Handle incoming A2A task request by directly calling orchestrate_pipeline."""
        try:
            logger.info(f"[supervisor] Received task request")
            # Extract context
            context = task_request.context or {}
            session_id = context.get("session_id")
            run_id = context.get("run_id")
            user_message = context.get("user_message")
            user_id = context.get("user_id")
            selected_parcel_ids = context.get("selected_parcel_ids")
            llm_provider = context.get("llm_provider")
            llm_model = context.get("llm_model")
            
            logger.info(f"[{run_id}] Received task request")
            logger.info(f"[{run_id}] task_id: {task_request.task_id}")
            logger.info(f"[{run_id}] task_description: {task_request.task_description[:200]}")
            logger.info(f"[{run_id}] context keys: {list(task_request.context.keys()) if task_request.context else None}")
            logger.info(f"[{run_id}] Extracted - session_id: {session_id}, user_id: {user_id}")
            
            if not all([session_id, run_id, user_message]):
                missing = []
                if not session_id:
                    missing.append("session_id")
                if not run_id:
                    missing.append("run_id")
                if not user_message:
                    missing.append("user_message")
                error_msg = f"Missing required context fields: {', '.join(missing)}"
                logger.error(f"[{run_id or 'unknown'}] {error_msg}")
                raise ValueError(error_msg)
            
            # Call orchestrate_pipeline off the event loop to avoid blocking
            skip_cache = context.get("skip_cache", False)
            result = await asyncio.to_thread(
                orchestrate_pipeline,
                session_id=session_id,
                run_id=run_id,
                user_message=user_message,
                user_id=user_id,
                skip_cache=skip_cache,
                selected_parcel_ids=selected_parcel_ids,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
            
            # Return as JSON string
            result_json = json.dumps(result)
            logger.info(f"[{run_id}] Task completed: {len(result_json)} chars")
            
            return TaskResponse(
                task_id=task_request.task_id,
                status="completed",
                result=result_json,
            )
            
        except Exception as e:
            # Extract run_id if available for error logging
            run_id = task_request.context.get("run_id", "unknown") if task_request.context else "unknown"
            logger.error(f"[{run_id}] Task failed: {e}", exc_info=True)
            return TaskResponse(
                task_id=task_request.task_id,
                status="failed",
                result=None,
                error=str(e),
            )
    
    @app.get("/health")
    async def health():
        return {"status": "healthy", "agent": "supervisor"}
    
    # Run the server
    logger.info(f"Starting Supervisor A2A server on port {SUPERVISOR_PORT}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=SUPERVISOR_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
