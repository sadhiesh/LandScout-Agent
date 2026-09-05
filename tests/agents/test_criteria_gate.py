"""Tests for the Supervisor's criteria sufficiency gate.

Fully offline. The LLM is stubbed everywhere (see tests/CLAUDE.md), and the
assertions are about routing and contracts — whether the gate asks, whether it
spends an LLM call — never about the wording it produces.
"""

from __future__ import annotations

import json

import pytest

from agents.supervisor.criteria_gate import (
    GateResult,
    apply_clarification_answer,
    assess_breadth,
    assess_criteria,
    assess_no_results,
    count_signals,
    inferred_locations,
    is_affirmative,
    is_search_confirmation,
    is_search_rejection,
    merge_criteria,
    missing_signals,
    pick_relax_candidate,
    stated_criteria,
)
from tools.scoring import get_gate_config


class LLMSpy:
    """Stub LLM that records calls and replays a canned response."""

    def __init__(self, response: object = None, raises: Exception | None = None):
        self._response = response
        self._raises = raises
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self._raises:
            raise self._raises
        if isinstance(self._response, str):
            return self._response
        return json.dumps(self._response)

    @property
    def called(self) -> bool:
        return bool(self.calls)


# Signal detection


def test_defaulted_state_is_not_a_signal() -> None:
    """A state the parser filled in must not make a bare request look specified."""
    assert count_signals({"state": "texas"}, {"state": "default"}) == []


def test_user_stated_fields_count_as_signals() -> None:
    criteria = {"state": "texas", "county": "collin", "price_max": 500_000}
    provenance = {"state": "default", "county": "user", "price_max": "user"}

    assert set(count_signals(criteria, provenance)) == {"location", "budget"}
    assert set(missing_signals(criteria, provenance)) == {"acreage", "intent"}


def test_empty_collections_are_not_signals() -> None:
    criteria = {"property_types": [], "keyword": ""}
    provenance = {"property_types": "user", "keyword": "user"}

    assert count_signals(criteria, provenance) == []


def test_signals_fall_back_to_non_null_without_provenance() -> None:
    assert count_signals({"county": "collin"}, None) == ["location"]


# Merging across a clarifying turn


def test_merge_prefers_new_values() -> None:
    merged = merge_criteria({"price_max": 300_000}, {"price_max": 400_000})
    assert merged["price_max"] == 400_000


def test_merge_keeps_prior_when_new_is_null() -> None:
    """A one-word answer must not wipe out the county named two turns ago."""
    merged = merge_criteria({"county": "collin"}, {"county": None, "price_max": 400_000})

    assert merged["county"] == "collin"
    assert merged["price_max"] == 400_000


def test_merge_does_not_mutate_inputs() -> None:
    prior = {"county": "collin"}
    new = {"price_max": 400_000}

    merge_criteria(prior, new)

    assert prior == {"county": "collin"}
    assert new == {"price_max": 400_000}


def test_clear_is_applied_before_replacement_patch() -> None:
    """Replacing a city must not clear the newly parsed city value."""
    prior = {
        "state": "texas",
        "city": "weston",
        "acres_min": 2,
        "acres_max": 5,
        "property_types": ["homesite"],
    }

    merged = merge_criteria(prior, {"city": "roland"}, ["city"])

    assert merged == {
        "state": "texas",
        "city": "roland",
        "county": None,
        "region": None,
        "acres_min": 2,
        "acres_max": 5,
        "property_types": ["homesite"],
    }


def test_new_location_scope_clears_prior_alternative_scope() -> None:
    merged = merge_criteria(
        {"state": "texas", "county": "collin", "acres_min": 2},
        {"city": "roland"},
    )

    assert merged["city"] == "roland"
    assert merged["county"] is None
    assert merged["acres_min"] == 2


# Stage 1: pre-search sufficiency


def test_stage1_passes_without_spending_an_llm_call() -> None:
    """The common path must be free — any real signal short-circuits."""
    llm = LLMSpy()

    result = assess_criteria(
        criteria={"state": "texas", "county": "collin"},
        provenance={"state": "default", "county": "user"},
        user_message="land in collin county",
        llm_fn=llm,
    )

    assert result.sufficient
    assert not llm.called


def test_stage1_asks_when_nothing_actionable_given() -> None:
    llm = LLMSpy(
        {
            "reasoning": "No place, budget, size or type.",
            "interpretations": ["recreational", "investment"],
            "sufficient": False,
            "missing_critical": ["location", "budget"],
            "question": "Whereabouts are you looking, and what's your budget?",
        }
    )

    result = assess_criteria(
        criteria={"state": "texas"},
        provenance={"state": "default"},
        user_message="I want to buy some land",
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.question
    assert set(result.missing) == {"location", "budget"}
    assert llm.called


def test_stage1_defers_to_llm_saying_sufficient() -> None:
    """The model may read intent the deterministic check cannot see."""
    llm = LLMSpy(
        {"reasoning": "Implies a region.", "sufficient": True, "question": None}
    )

    result = assess_criteria(
        criteria={"state": "texas"},
        provenance={"state": "default"},
        user_message="somewhere out past the metroplex",
        llm_fn=llm,
    )

    assert result.sufficient
    assert result.question is None


def test_stage1_stops_asking_at_the_round_cap() -> None:
    llm = LLMSpy({"sufficient": False, "question": "again?"})
    max_rounds = get_gate_config()["max_rounds"]

    result = assess_criteria(
        criteria={"state": "texas"},
        provenance={"state": "default"},
        user_message="dunno",
        round_num=max_rounds,
        llm_fn=llm,
    )

    assert result.sufficient
    assert not llm.called, "must not keep interrogating past the cap"


def test_stage1_parses_a_fenced_llm_response() -> None:
    """Contract with extract_json — CrewAI wraps JSON in markdown (ADR 0015)."""
    llm = LLMSpy(
        '```json\n{"sufficient": false, "question": "Where?", '
        '"missing_critical": ["location"]}\n```'
    )

    result = assess_criteria(
        criteria={},
        provenance={},
        user_message="land please",
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.question == "Where?"


@pytest.mark.parametrize(
    "llm",
    [
        LLMSpy(raises=RuntimeError("gateway down")),
        LLMSpy("not json at all"),
    ],
    ids=["llm_error", "unparseable"],
)
def test_stage1_fails_open(llm: LLMSpy) -> None:
    """A broken gate must never stop someone from searching."""
    result = assess_criteria(
        criteria={"state": "texas"},
        provenance={"state": "default"},
        user_message="I want land",
        llm_fn=llm,
    )

    assert result.sufficient


# Stage 2: post-search breadth


def _parcels(count: int) -> list[dict]:
    return [
        {
            "property_id": str(index),
            "location": {"city": "Mckinney", "state": "TX"},
            "basic_info": {
                "price": 100_000 + index * 10_000,
                "acres": 5 + index,
                "property_types": ["undeveloped"],
            },
        }
        for index in range(count)
    ]


def test_stage2_accepts_a_workable_result_set_for_free() -> None:
    llm = LLMSpy()

    result = assess_breadth(
        criteria={"state": "texas"},
        parcels=_parcels(8),
        candidate_limit=10,
        total_matching=8,
        provenance={"state": "default"},
        llm_fn=llm,
    )

    assert result.sufficient
    assert not llm.called


def test_stage2_asks_when_the_set_is_too_broad() -> None:
    llm = LLMSpy(
        {
            "reasoning": "Prices and sizes span useful ranges.",
            "common_conditions": ["Most parcels are in Mckinney."],
            "recommendations": ["Choose a maximum price."],
            "question": "Select up to 10 parcels or narrow your budget.",
        }
    )

    result = assess_breadth(
        criteria={"state": "texas"},
        parcels=_parcels(11),
        candidate_limit=10,
        total_matching=12_403,
        provenance={"state": "default"},
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.question
    assert result.common_conditions
    assert result.recommendations
    assert llm.called


def test_stage2_hard_cap_applies_to_fully_specified_search() -> None:
    criteria = {
        "county": "collin",
        "price_max": 500_000,
        "acres_min": 20,
        "property_types": ["undeveloped"],
    }
    provenance = {key: "user" for key in criteria}
    llm = LLMSpy()

    result = assess_breadth(
        criteria=criteria,
        parcels=_parcels(11),
        candidate_limit=10,
        total_matching=12_403,
        provenance=provenance,
        llm_fn=llm,
    )

    assert not result.sufficient
    assert llm.called


def test_stage2_hard_cap_does_not_depend_on_missing_signals() -> None:
    criteria = {
        "county": "collin",
        "price_max": 500_000,
        "acres_min": 20,
        "acres_max": 50,
    }
    provenance = {key: "user" for key in criteria}
    llm = LLMSpy()

    result = assess_breadth(
        criteria=criteria,
        parcels=_parcels(11),
        candidate_limit=10,
        total_matching=340,
        provenance=provenance,
        llm_fn=llm,
    )

    assert not result.sufficient
    assert llm.called


def test_stage2_asks_when_a_narrowing_signal_is_missing() -> None:
    llm = LLMSpy({"question": "What's your budget?"})

    result = assess_breadth(
        criteria={"county": "collin", "acres_min": 20},
        parcels=_parcels(11),
        candidate_limit=10,
        total_matching=12_403,
        provenance={"county": "user", "acres_min": "user"},
        llm_fn=llm,
    )

    assert not result.sufficient
    assert llm.called


def test_stage2_hard_cap_survives_the_round_cap() -> None:
    llm = LLMSpy({"question": "narrow further?"})
    max_rounds = get_gate_config()["max_rounds"]

    result = assess_breadth(
        criteria={"state": "texas"},
        parcels=_parcels(11),
        candidate_limit=10,
        total_matching=12_403,
        provenance={"state": "default"},
        round_num=max_rounds,
        llm_fn=llm,
    )

    assert not result.sufficient
    assert llm.called


def test_stage2_fails_safe_with_fallback_recommendations() -> None:
    llm = LLMSpy(raises=RuntimeError("gateway down"))

    result = assess_breadth(
        criteria={"state": "texas"},
        parcels=_parcels(11),
        candidate_limit=10,
        total_matching=12_403,
        provenance={"state": "default"},
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.question
    assert result.common_conditions
    assert result.recommendations


# Configuration invariants


def test_gate_config_thresholds_are_coherent() -> None:
    config = get_gate_config()

    assert config["max_rounds"] >= 1
    assert config["min_signals"] >= 1


# Round-trip through the message log
#
# api/chat.py persists a turn as several rows: one per journey step, then a
# summary carrying the payload. The clarification state rides on that summary,
# so the lookup has to scan the whole turn rather than just the last row.


class FakeStore:
    """Stands in for PostgresStore, replaying a fixed message list."""

    def __init__(self, messages: list[dict]):
        self._messages = messages

    def __enter__(self) -> "FakeStore":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get_messages(self, session_id: str) -> list[dict]:
        return self._messages


def _turn(clarification: dict | None) -> list[dict]:
    """Messages as api/chat.py writes them for one clarifying turn."""
    summary_payload: dict = {"shortlist": [], "total_matching": 0, "criteria": {}}
    if clarification:
        summary_payload["clarification"] = clarification

    return [
        {"role": "user", "content": "I want land", "payload": None},
        {"role": "assistant", "content": "Parsing...", "payload": {"journey_step": True}},
        {"role": "assistant", "content": "Need more", "payload": {"journey_step": True}},
        {"role": "assistant", "content": "Where?", "payload": summary_payload},
    ]


def test_pending_clarification_survives_the_journey_step_rows(monkeypatch) -> None:
    import memory.store

    from agents.supervisor.supervisor import _load_pending_clarification

    clarification = {
        "round": 1,
        "stage": 1,
        "pending_criteria": {"state": "texas", "county": "collin"},
        "pending_provenance": {"state": "default", "county": "user"},
        "missing": ["budget"],
    }
    monkeypatch.setattr(
        memory.store, "PostgresStore", lambda *a, **k: FakeStore(_turn(clarification))
    )

    pending = _load_pending_clarification("s1")

    assert pending["pending_criteria"]["county"] == "collin"
    assert pending["pending_provenance"]["county"] == "user"
    assert pending["round"] == 1


def test_no_pending_clarification_after_a_normal_turn(monkeypatch) -> None:
    import memory.store

    from agents.supervisor.supervisor import _load_pending_clarification

    monkeypatch.setattr(
        memory.store, "PostgresStore", lambda *a, **k: FakeStore(_turn(None))
    )

    assert _load_pending_clarification("s1") == {}


def test_pending_clarification_stops_at_the_previous_user_turn(monkeypatch) -> None:
    """An answered question from two turns ago must not be picked up again."""
    import memory.store

    from agents.supervisor.supervisor import _load_pending_clarification

    stale = {"round": 1, "pending_criteria": {"county": "stale"}}
    messages = _turn(stale) + [
        {"role": "user", "content": "collin county", "payload": None},
        {"role": "assistant", "content": "Found 12", "payload": {"shortlist": [1]}},
    ]
    monkeypatch.setattr(
        memory.store, "PostgresStore", lambda *a, **k: FakeStore(messages)
    )

    assert _load_pending_clarification("s1") == {}


def test_pending_clarification_survives_a_dead_database(monkeypatch) -> None:
    import memory.store

    from agents.supervisor.supervisor import _load_pending_clarification

    def boom(*args: object, **kwargs: object):
        raise RuntimeError("postgres down")

    monkeypatch.setattr(memory.store, "PostgresStore", boom)

    assert _load_pending_clarification("s1") == {}


# Confirming an inferred location
#
# The parser fills in state "texas" from "McKinney" without the user saying so.
# Provenance marks that "inferred", and the gate confirms it before searching.


def test_inferred_location_is_confirmed_before_searching() -> None:
    """The McKinney case: enough to search on, but Texas was a guess."""
    llm = LLMSpy(
        {
            "reasoning": "McKinney is probably the Texas one but they never said.",
            "question": "I'll take that as McKinney, Texas — budget in mind?",
        }
    )

    result = assess_criteria(
        criteria={
            "state": "texas",
            "city": "mckinney",
            "property_types": ["recreational"],
            "keyword": "creek access",
        },
        provenance={
            "state": "inferred",
            "city": "user",
            "property_types": "user",
            "keyword": "user",
        },
        user_message="Recreational land in McKinney with creek access",
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.confirmed_fields == ["state"]
    assert llm.called


def test_a_stated_location_is_not_confirmed() -> None:
    """Saying "Texas" outright must not earn a question about Texas."""
    llm = LLMSpy()

    result = assess_criteria(
        criteria={"state": "texas", "city": "mckinney"},
        provenance={"state": "user", "city": "user"},
        user_message="land in McKinney, Texas",
        llm_fn=llm,
    )

    assert result.sufficient
    assert not llm.called


def test_inferred_locations_reports_only_guesses() -> None:
    criteria = {"state": "texas", "city": "mckinney", "county": None}
    provenance = {"state": "inferred", "city": "user", "county": "default"}

    assert inferred_locations(criteria, provenance) == ["state"]


def test_answering_a_confirmation_counts_as_assent() -> None:
    """Having been asked once, the same assumption must not be raised again."""
    pending = {"confirmed_fields": ["state"], "pending_criteria": {"state": "texas"}}

    criteria, provenance, notes = apply_clarification_answer(
        {"state": "texas", "city": "mckinney"},
        {"state": "inferred", "city": "user"},
        pending,
        "yes",
    )

    assert provenance["state"] == "user"
    assert notes

    # And on the next pass the gate stays quiet.
    llm = LLMSpy()
    assert assess_criteria(criteria, provenance, "yes", llm_fn=llm).sufficient
    assert not llm.called


# Zero results — offering to relax rather than dead-ending


def test_pick_relax_candidate_prefers_the_keyword() -> None:
    """LandWatch matches keyword as literal text, so it is the usual culprit."""
    candidate = pick_relax_candidate(
        {
            "city": "mckinney",
            "property_types": ["recreational"],
            "keyword": "creek access",
            "price_max": 500_000,
        }
    )

    assert candidate["field"] == "keyword"
    assert candidate["value"] == "creek access"


def test_pick_relax_candidate_falls_through_priority() -> None:
    candidate = pick_relax_candidate({"city": "mckinney", "price_max": 500_000})

    assert candidate["field"] == "price_max"


def test_pick_relax_candidate_returns_none_when_nothing_to_drop() -> None:
    assert pick_relax_candidate({"state": "texas", "county": "collin"}) is None


def test_zero_results_offers_to_drop_the_keyword() -> None:
    llm = LLMSpy(
        {
            "reasoning": "Keyword is literal-matched.",
            "question": "Nothing came back. Want me to search again without 'creek access'?",
        }
    )

    result = assess_no_results(
        criteria={
            "city": "mckinney",
            "property_types": ["recreational"],
            "keyword": "creek access",
        },
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.relax_suggestion["field"] == "keyword"
    assert llm.called


def test_zero_results_stays_quiet_when_there_is_nothing_to_relax() -> None:
    llm = LLMSpy()

    result = assess_no_results(criteria={"state": "texas"}, llm_fn=llm)

    assert result.sufficient
    assert not llm.called


def test_zero_results_still_recommends_relaxing_at_the_round_cap() -> None:
    llm = LLMSpy({"question": "drop something else?"})
    max_rounds = get_gate_config()["max_rounds"]

    result = assess_no_results(
        criteria={"keyword": "creek"},
        round_num=max_rounds,
        llm_fn=llm,
    )

    assert not result.sufficient
    assert result.relax_suggestion
    assert llm.called


def test_zero_results_uses_fallback_recommendation_when_llm_fails() -> None:
    result = assess_no_results(
        criteria={"keyword": "creek"},
        llm_fn=LLMSpy(raises=RuntimeError("gateway down")),
    )

    assert not result.sufficient
    assert result.question
    assert result.relax_suggestion


# Applying an accepted relax offer


@pytest.mark.parametrize(
    "reply", ["yes", "Yes.", "yeah", "sure", "ok", "please do", "go ahead", "Do it!"]
)
def test_affirmative_replies_are_recognised(reply: str) -> None:
    assert is_affirmative(reply)


@pytest.mark.parametrize(
    "reply",
    ["no", "not really", "keep it", "yes but only in collin", "under 500k", ""],
)
def test_non_affirmative_replies_are_not(reply: str) -> None:
    """Anything unrecognised must read as no — dropping a wanted filter is worse."""
    assert not is_affirmative(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "yes",
        "Yes, run it.",
        "yes please run the search",
        "go ahead",
        "looks good",
        "approved",
    ],
)
def test_unambiguous_search_confirmations_are_recognised(reply: str) -> None:
    assert is_search_confirmation(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "remove it",
        "drop it",
        "fine",
        "right",
        "correct",
        "search 2000",
        "yes, but remove the price limit",
    ],
)
def test_change_requests_do_not_approve_search(reply: str) -> None:
    assert not is_search_confirmation(reply)


@pytest.mark.parametrize("reply", ["no", "cancel", "stop", "never mind"])
def test_search_rejections_are_recognised(reply: str) -> None:
    assert is_search_rejection(reply)


def test_agreeing_drops_the_offered_filter() -> None:
    pending = {
        "relax_suggestion": {
            "field": "keyword",
            "label": "keyword",
            "value": "creek access",
        }
    }

    criteria, provenance, notes = apply_clarification_answer(
        {"city": "mckinney", "keyword": "creek access"},
        {"city": "user", "keyword": "user"},
        pending,
        "yes please",
    )

    assert criteria["keyword"] is None
    assert provenance["keyword"] == "relaxed"
    assert notes


def test_declining_keeps_the_filter() -> None:
    pending = {
        "relax_suggestion": {
            "field": "keyword",
            "label": "keyword",
            "value": "creek access",
        }
    }

    criteria, _, notes = apply_clarification_answer(
        {"city": "mckinney", "keyword": "creek access"},
        {"city": "user", "keyword": "user"},
        pending,
        "no, keep the creek",
    )

    assert criteria["keyword"] == "creek access"
    assert not notes


def test_apply_clarification_answer_does_not_mutate_inputs() -> None:
    criteria = {"keyword": "creek"}
    provenance = {"keyword": "user"}
    pending = {"relax_suggestion": {"field": "keyword", "value": "creek"}}

    apply_clarification_answer(criteria, provenance, pending, "yes")

    assert criteria == {"keyword": "creek"}
    assert provenance == {"keyword": "user"}


# Defaults must never masquerade as user input
#
# "need land" once produced a Texas, $100k-$1M, 10-100 acre, three-property-type
# search. Two bugs compounded: the parse crashed and fell back to the whole
# config defaults block, and Stage 1 was then shown those defaults and reasoned
# that the user had given plenty to go on.

# The defaults block as it stood when this happened. It has since been trimmed
# to `state` alone, but these tests deliberately keep the full literal: the
# guarantee is that a populated criteria dict the user never asked for cannot
# buy a search, whatever the config happens to contain.
CONFIG_DEFAULTS = {
    "state": "texas",
    "price_min": 100_000,
    "price_max": 1_000_000,
    "acres_min": 10,
    "acres_max": 100,
    "property_types": ["farms_and_ranches", "undeveloped", "recreational"],
}


def test_config_defaults_stay_minimal() -> None:
    """Only `state` may be supplied on the user's behalf.

    Anything else here becomes a real search constraint that hides parcels
    the user never chose to exclude.
    """
    from tools.scoring import get_defaults

    assert set(get_defaults()) == {"state"}


def test_stated_criteria_hides_defaults_and_inferences() -> None:
    provenance = dict.fromkeys(CONFIG_DEFAULTS, "default")

    assert stated_criteria(CONFIG_DEFAULTS, provenance) == {}


def test_stated_criteria_keeps_only_what_the_user_said() -> None:
    criteria = {"state": "texas", "city": "mckinney", "price_max": 500_000}
    provenance = {"state": "inferred", "city": "user", "price_max": "default"}

    assert stated_criteria(criteria, provenance) == {"city": "mckinney"}


def test_defaults_alone_do_not_count_as_signals() -> None:
    """A config default is not something the user asked for."""
    provenance = dict.fromkeys(CONFIG_DEFAULTS, "default")

    assert count_signals(CONFIG_DEFAULTS, provenance) == []


def test_need_land_asks_even_when_defaults_are_populated() -> None:
    """The reported regression: a full defaults block must not buy a search."""
    llm = LLMSpy(
        {
            "reasoning": "They gave no place, budget, size or type.",
            "sufficient": False,
            "missing_critical": ["location", "budget"],
            "question": "Whereabouts are you looking, and what's your budget?",
        }
    )

    result = assess_criteria(
        criteria=dict(CONFIG_DEFAULTS),
        provenance=dict.fromkeys(CONFIG_DEFAULTS, "default"),
        user_message="need land",
        llm_fn=llm,
    )

    assert not result.sufficient, "defaults must not stand in for user intent"
    assert llm.called


def test_stage1_prompt_never_shows_the_model_a_default() -> None:
    """Belt and braces: the values must not reach the prompt text at all.

    Asserting on the outcome is not enough — the model talked itself into
    searching last time precisely because it could see these numbers.
    """
    llm = LLMSpy({"sufficient": False, "question": "Where?"})

    assess_criteria(
        criteria=dict(CONFIG_DEFAULTS),
        provenance=dict.fromkeys(CONFIG_DEFAULTS, "default"),
        user_message="need land",
        llm_fn=llm,
    )

    prompt = llm.calls[0]
    assert "1000000" not in prompt
    assert "farms_and_ranches" not in prompt
    assert "nothing at all" in prompt


# Parser behaviour on a bare request
#
# The parse for "need land" correctly returned every key as null, then crashed
# on `parsed.get("state", default)` — dict.get only falls back on a *missing*
# key, not a present-but-null one — and the except branch substituted the whole
# config defaults block.


class _NullEmitter:
    def emit(self, *args: object, **kwargs: object) -> None:
        pass


def _stub_crew(monkeypatch, result: object) -> None:
    """Point the parser at a canned LLM response instead of the gateway."""
    import crewai

    from agents.supervisor import supervisor as sup

    monkeypatch.setattr(
        sup,
        "create_supervisor_agent",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(crewai, "Task", lambda **kwargs: None)

    class StubCrew:
        def __init__(self, **kwargs: object) -> None:
            pass

        def kickoff(self) -> object:
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(crewai, "Crew", StubCrew)


def test_all_null_parse_does_not_crash_on_the_state_key(monkeypatch) -> None:
    """A present-but-null state must fall back, not raise."""
    from agents.supervisor import supervisor as sup

    all_null = {key: None for key in ("state", "county", "city", "region")}
    all_null["_stated_fields"] = []
    _stub_crew(monkeypatch, json.dumps(all_null))

    criteria, provenance, resolution = sup._parse_criteria_with_llm(
        "need land", "run-1", _NullEmitter()
    )

    assert criteria["state"] == "texas"
    assert provenance["state"] == "default"
    assert criteria.get("price_max") is None, "must not invent a budget"
    assert criteria.get("acres_min") is None, "must not invent an acreage"
    assert resolution["intent"] == "search"


def test_model_derived_state_is_inferred_not_default(monkeypatch) -> None:
    """The three provenance values must stay distinct.

    A state the model worked out from "McKinney" is worth confirming. A state
    that came from config because nobody said anything is not — that deserves
    "where are you looking?", not "did you mean Texas?".
    """
    from agents.supervisor import supervisor as sup

    _stub_crew(
        monkeypatch,
        json.dumps(
            {
                "state": "texas",
                "city": "mckinney",
                "property_types": ["recreational"],
                "_stated_fields": ["city", "property_types"],
            }
        ),
    )

    _, provenance, _ = sup._parse_criteria_with_llm(
        "Recreational land in McKinney", "run-1", _NullEmitter()
    )

    assert provenance["state"] == "inferred"
    assert provenance["city"] == "user"
    assert provenance["property_types"] == "user"
    assert provenance["price_max"] == "default"


def test_parse_failure_returns_nothing_it_cannot_justify(monkeypatch) -> None:
    """A failed parse must look unspecified, not like a detailed request."""
    from agents.supervisor import supervisor as sup

    _stub_crew(monkeypatch, RuntimeError("gateway down"))

    criteria, provenance, resolution = sup._parse_criteria_with_llm(
        "need land", "run-1", _NullEmitter()
    )

    assert criteria == {"state": "texas"}
    assert provenance == {"state": "default"}
    for invented in ("price_min", "price_max", "acres_min", "property_types"):
        assert invented not in criteria
    assert resolution["intent"] == "search"

    # And the gate treats that as nothing to go on.
    assert count_signals(criteria, provenance) == []


def test_follow_up_parse_reports_explicit_range_clear(monkeypatch) -> None:
    """An open-ended minimum must explicitly remove the prior maximum."""
    from agents.supervisor import supervisor as sup

    _stub_crew(
        monkeypatch,
        json.dumps(
            {
                "_turn_intent": "search",
                "_answer": None,
                "_clear_fields": ["acres_max"],
                "acres_min": 5,
                "acres_max": None,
                "_stated_fields": ["acres_min"],
            }
        ),
    )

    criteria, _, resolution = sup._parse_criteria_with_llm(
        "make it 5 acres and above",
        "run-1",
        _NullEmitter(),
        current_criteria={"state": "texas", "acres_min": 10, "acres_max": 20},
    )

    assert criteria["acres_min"] == 5
    assert criteria["state"] is None, "unstated default must not replace session state"
    assert resolution["clear_fields"] == ["acres_max"]


def test_result_question_parse_returns_grounded_answer_intent(monkeypatch) -> None:
    from agents.supervisor import supervisor as sup

    _stub_crew(
        monkeypatch,
        json.dumps(
            {
                "_turn_intent": "results_question",
                "_answer": "Parcel p1 ranked first because of its lower price.",
                "_clear_fields": [],
                "_stated_fields": [],
            }
        ),
    )

    _, _, resolution = sup._parse_criteria_with_llm(
        "Why is the first parcel ranked highest?",
        "run-1",
        _NullEmitter(),
        current_criteria={"county": "collin"},
        current_results=[{"property_id": "p1", "rank": 1, "price": 200_000}],
    )

    assert resolution["intent"] == "results_question"
    assert "p1" in resolution["answer"]


# End-to-end conversation
#
# The reported case: "Recreational land in McKinney with creek access" silently
# assumed Texas and then dead-ended on zero results. Three turns now get the
# user to a real search.


def test_mckinney_conversation_reaches_a_search() -> None:
    def stub(prompt: str) -> str:
        if "no results at all" in prompt:
            return json.dumps({"question": "Drop the creek access wording?"})
        if "you worked out a location" in prompt:
            return json.dumps({"question": "McKinney, Texas? Any budget?"})
        return json.dumps({"sufficient": True, "question": None})

    criteria = {
        "state": "texas",
        "city": "mckinney",
        "property_types": ["recreational"],
        "keyword": "creek access",
    }
    provenance = {
        "state": "inferred",
        "city": "user",
        "property_types": "user",
        "keyword": "user",
    }

    # Turn 1 — Texas was a guess, so confirm it before burning a search.
    turn1 = assess_criteria(
        criteria, provenance, "Recreational land in McKinney with creek access",
        round_num=0, llm_fn=stub,
    )
    assert not turn1.sufficient
    assert turn1.confirmed_fields == ["state"]

    pending = {
        "round": 1,
        "pending_criteria": criteria,
        "pending_provenance": provenance,
        "confirmed_fields": turn1.confirmed_fields,
        "relax_suggestion": turn1.relax_suggestion,
    }

    # Turn 2 — "yes" settles the location, the search runs, and finds nothing.
    criteria, provenance, _ = apply_clarification_answer(
        merge_criteria(pending["pending_criteria"], {}),
        dict(pending["pending_provenance"]),
        pending,
        "yes",
    )
    assert provenance["state"] == "user"
    assert assess_criteria(criteria, provenance, "yes", 1, llm_fn=stub).sufficient

    turn2 = assess_no_results(criteria, round_num=1, llm_fn=stub)
    assert not turn2.sufficient
    assert turn2.relax_suggestion["field"] == "keyword"

    pending = {
        "round": 2,
        "pending_criteria": criteria,
        "pending_provenance": provenance,
        "confirmed_fields": [],
        "relax_suggestion": turn2.relax_suggestion,
    }

    # Turn 3 — "yes" drops the keyword and the search goes ahead without it.
    criteria, provenance, notes = apply_clarification_answer(
        merge_criteria(pending["pending_criteria"], {}),
        dict(pending["pending_provenance"]),
        pending,
        "yes",
    )
    assert criteria["keyword"] is None
    assert criteria["city"] == "mckinney", "relaxing must not lose the location"
    assert criteria["property_types"] == ["recreational"]
    assert notes
    assert assess_criteria(criteria, provenance, "yes", 2, llm_fn=stub).sufficient


# Trace emission


def test_gate_survives_a_broken_emitter() -> None:
    """Trace failures must not take down the pipeline."""

    class BrokenEmitter:
        def emit(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("redis gone")

    result = assess_criteria(
        criteria={"county": "collin"},
        provenance={"county": "user"},
        user_message="land in collin",
        emitter=BrokenEmitter(),
        llm_fn=LLMSpy(),
    )

    assert result.sufficient


def test_gate_emits_thought_events() -> None:
    events: list[tuple[str, str, dict]] = []

    class RecordingEmitter:
        def emit(self, kind: str, summary: str, data: dict) -> None:
            events.append((kind, summary, data))

    assess_criteria(
        criteria={"county": "collin"},
        provenance={"county": "user"},
        user_message="land in collin",
        emitter=RecordingEmitter(),
        llm_fn=LLMSpy(),
    )

    assert events
    assert all(kind == "thought" for kind, _, _ in events)
    assert events[0][2]["stage"] == 1
