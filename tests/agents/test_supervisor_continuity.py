"""Offline tests for Supervisor candidate and session continuity helpers."""

from __future__ import annotations

from typing import Any
import json

import memory.store

from agents.supervisor.criteria_gate import GateResult
from agents.supervisor.supervisor import (
    _combine_cached_results,
    _criteria_confirmation_message,
    _has_active_criteria,
    _load_session_context,
    _resolve_candidate_selection,
    compute_criteria_fingerprint,
)


class FakeStore:
    messages: list[dict[str, Any]] = []
    searches: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> "FakeStore":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.messages

    def get_search(self, run_id: str) -> dict[str, Any] | None:
        return self.searches.get(run_id)


def _candidate(property_id: str) -> dict[str, Any]:
    return {
        "property_id": property_id,
        "location": {"city": "Mckinney", "state": "TX"},
        "basic_info": {"price": 250_000, "acres": 10},
    }


def test_confirmation_message_includes_unrecognised_active_criteria() -> None:
    message = _criteria_confirmation_message(
        {"state": "texas", "sale_pending": False, "date_listed": "this-week"}
    )

    assert "State: Texas" in message
    assert "Sale Pending: No" in message
    assert "Date Listed: This Week" in message


def test_all_null_criteria_are_not_approvable() -> None:
    assert not _has_active_criteria(
        {"state": None, "county": None, "price_max": None}
    )


def test_session_context_recovers_latest_criteria_and_scored_results(
    monkeypatch,
) -> None:
    FakeStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": {"county": "collin", "price_max": 500_000},
                "shortlist": [_candidate("p1")],
            },
        },
        {
            "role": "assistant",
            "payload": {
                "criteria": {"county": "collin", "price_max": 400_000},
                "criteria_provenance": {
                    "county": "user",
                    "price_max": "user",
                },
                "shortlist": [_candidate("p2")],
            },
        },
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    context = _load_session_context("session-1")

    assert context["criteria"]["price_max"] == 400_000
    assert context["shortlist"][0]["property_id"] == "p2"
    assert context["provenance"]["price_max"] == "user"


def test_session_context_skips_pending_confirmation_with_empty_results(
    monkeypatch,
) -> None:
    FakeStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": {"city": "weston"},
                "criteria_provenance": {"city": "user"},
                "shortlist": [_candidate("saved")],
            },
        },
        {
            "role": "assistant",
            "payload": {
                "criteria": {"city": "roland"},
                "criteria_provenance": {"city": "user"},
                "shortlist": [],
                "awaiting_clarification": True,
                "clarification": {
                    "kind": "criteria_confirmation",
                    "pending_criteria": {"city": "roland"},
                },
            },
        },
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    context = _load_session_context("session-1")

    assert context["criteria"] == {"city": "weston"}
    assert context["shortlist"][0]["property_id"] == "saved"


def test_session_context_skips_error_summary_with_empty_results(
    monkeypatch,
) -> None:
    FakeStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": {"city": "weston"},
                "criteria_provenance": {"city": "user"},
                "shortlist": [_candidate("saved")],
            },
        },
        {
            "role": "assistant",
            "payload": {
                "criteria": {"county": "denton"},
                "shortlist": [],
                "error": "unsupported_county",
            },
        },
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    context = _load_session_context("session-1")

    assert context["criteria"] == {"city": "weston"}
    assert context["shortlist"][0]["property_id"] == "saved"


def test_session_context_does_not_pair_new_criteria_with_stale_results(
    monkeypatch,
) -> None:
    FakeStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": {"county": "collin"},
                "criteria_provenance": {"county": "user"},
                "shortlist": [_candidate("old")],
            },
        },
        {
            "role": "assistant",
            "payload": {
                "criteria": {"county": "collin", "price_max": 300_000},
                "criteria_provenance": {
                    "county": "user",
                    "price_max": "user",
                },
                "shortlist": [],
                "candidates": [_candidate("new")],
            },
        },
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    context = _load_session_context("session-1")

    assert context["criteria"]["price_max"] == 300_000
    assert context["provenance"]["price_max"] == "user"
    assert context["shortlist"] == []


def test_cached_rows_are_rebuilt_as_canonical_scored_parcels() -> None:
    combined = _combine_cached_results(
        [
            {
                "parcel_id": "p1",
                "total_score": 88.0,
                "dimension_scores": {"acreage_fit": 0.9},
                "rationale": "Strong acreage fit.",
                "highlights": [{"label": "Acreage", "detail": "Strong fit"}],
                "drawbacks": [{"label": "Price", "detail": "Above target"}],
                "considerations": ["Verify access."],
            }
        ],
        [
            {
                "parcel_id": "p1",
                "location": {"city": "Mckinney"},
                "basic_info": {"price": 250_000, "acres": 10},
            }
        ],
        10,
        enrichments_by_id={"p1": {"cad_parcel": {"status": "ok"}}},
    )

    assert combined[0]["property_id"] == "p1"
    assert combined[0]["basic_info"]["price"] == 250_000
    assert combined[0]["score"] == 88.0
    assert combined[0]["score_breakdown"]["dimensions"]["acreage_fit"] == 0.9
    assert combined[0]["score_breakdown"]["highlights"]
    assert combined[0]["considerations"] == ["Verify access."]
    assert combined[0]["enrichment"]["cad_parcel"]["status"] == "ok"


def test_candidate_selection_reuses_only_selected_saved_parcels(monkeypatch) -> None:
    FakeStore.searches = {
        "run-1": {
            "session_id": "session-1",
            "listings": [_candidate("p1"), _candidate("p2"), _candidate("p3")],
            "total_matching": 50,
        }
    }
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    parcels, search, error = _resolve_candidate_selection(
        "session-1", "run-1", ["p3", "p1"], 10
    )

    assert error is None
    assert search is not None
    assert [parcel["property_id"] for parcel in parcels] == ["p3", "p1"]


def test_candidate_selection_rejects_unknown_or_oversized_sets(monkeypatch) -> None:
    FakeStore.searches = {
        "run-1": {
            "session_id": "session-1",
            "listings": [_candidate("p1")],
        }
    }
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    _, search, unknown_error = _resolve_candidate_selection(
        "session-1", "run-1", ["missing"], 10
    )
    _, _, oversized_error = _resolve_candidate_selection(
        "session-1", "run-1", [str(index) for index in range(11)], 10
    )

    assert search is not None
    assert "not part" in unknown_error
    assert "no more than 10" in oversized_error


def test_candidate_selection_cannot_cross_sessions(monkeypatch) -> None:
    FakeStore.searches = {
        "run-1": {
            "session_id": "other-session",
            "listings": [_candidate("p1")],
        }
    }
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)

    parcels, _, error = _resolve_candidate_selection(
        "session-1", "run-1", ["p1"], 10
    )

    assert parcels == []
    assert "no longer available" in error


def test_search_amendment_preserves_prior_criteria_and_waits_for_confirmation(
    monkeypatch,
) -> None:
    from datetime import datetime, timezone

    from agents.common import trace
    from agents.supervisor import supervisor
    from memory.schemas import TraceEvent

    class ConfirmationStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {"session_id": session_id, "user_id": "user-1", "title": "Search"}

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Emitter:
        def emit(
            self,
            kind: str,
            summary: str,
            data: dict[str, Any] | None = None,
        ) -> None:
            TraceEvent(
                run_id="run-confirm",
                ts=datetime.now(timezone.utc),
                agent="supervisor",
                kind=kind,
                summary=summary,
                data=data,
            )

        def close(self) -> None:
            return None

    class Client:
        def __init__(self, *args: Any, **kwargs: Any):
            raise AssertionError("Scout must not be created before confirmation")

    prior_criteria = {
        "state": "texas",
        "city": "weston",
        "acres_min": 2,
        "acres_max": 5,
        "property_types": ["homesite"],
    }
    ConfirmationStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": prior_criteria,
                "criteria_provenance": {
                    key: "user" for key in prior_criteria
                },
                "shortlist": [_candidate("p1")],
            },
        }
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", ConfirmationStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(supervisor, "A2ACrewClient", Client)
    monkeypatch.setattr(
        supervisor,
        "_parse_criteria_with_llm",
        lambda *args, **kwargs: (
            {"state": "texas", "city": "roland"},
            {"state": "user", "city": "user"},
            {"intent": "search", "answer": None, "clear_fields": ["city"]},
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "assess_criteria",
        lambda **kwargs: GateResult(sufficient=True),
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-confirm",
        user_message="apply the same criteria in Roland, Texas",
        user_id="user-1",
    )

    assert result["awaiting_clarification"] is True
    assert result["clarification"]["kind"] == "criteria_confirmation"
    assert result["criteria"]["city"] == "roland"
    assert result["criteria"]["acres_min"] == 2
    assert result["criteria"]["acres_max"] == 5
    assert result["criteria"]["property_types"] == ["homesite"]
    assert "City: Roland" in result["message"]
    assert "Minimum acres: 2" in result["message"]
    assert "Property types: Homesite" in result["message"]


def test_correction_updates_pending_criteria_and_requests_confirmation_again(
    monkeypatch,
) -> None:
    from agents.common import trace
    from agents.supervisor import supervisor

    class ConfirmationStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {"session_id": session_id, "user_id": "user-1", "title": "Search"}

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Emitter:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

    pending_criteria = {
        "state": "texas",
        "city": "roland",
        "acres_min": 2,
        "acres_max": 5,
        "property_types": ["homesite"],
    }
    ConfirmationStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": pending_criteria,
                "shortlist": [],
                "clarification": {
                    "kind": "criteria_confirmation",
                    "round": 0,
                    "pending_criteria": pending_criteria,
                    "pending_provenance": {
                        key: "user" for key in pending_criteria
                    },
                    "original_run_id": "run-original",
                },
            },
        }
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", ConfirmationStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(
        supervisor,
        "A2ACrewClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scout must not run before revised confirmation")
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "_parse_criteria_with_llm",
        lambda *args, **kwargs: (
            {"price_max": 500_000},
            {"price_max": "user"},
            {"intent": "search", "answer": None, "clear_fields": []},
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "assess_criteria",
        lambda **kwargs: GateResult(sufficient=True),
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-correction",
        user_message="also keep it under $500k",
        user_id="user-1",
    )

    assert result["clarification"]["kind"] == "criteria_confirmation"
    assert result["criteria"]["city"] == "roland"
    assert result["criteria"]["property_types"] == ["homesite"]
    assert result["criteria"]["price_max"] == 500_000
    assert "Maximum price: $500,000" in result["message"]


def test_result_question_is_answered_without_search_confirmation(
    monkeypatch,
) -> None:
    from agents.common import trace
    from agents.supervisor import supervisor

    class ResultStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {"session_id": session_id, "user_id": "user-1", "title": "Search"}

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Emitter:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

        def memory_read(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

    ResultStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": {"state": "texas", "city": "roland"},
                "criteria_provenance": {"state": "user", "city": "user"},
                "shortlist": [_candidate("p1")],
            },
        },
        {
            "role": "assistant",
            "payload": {
                "criteria": {"state": "texas", "city": "weston"},
                "shortlist": [],
                "awaiting_clarification": True,
                "clarification": {
                    "kind": "criteria_confirmation",
                    "pending_criteria": {"state": "texas", "city": "weston"},
                    "pending_provenance": {
                        "state": "user",
                        "city": "user",
                    },
                    "original_run_id": "run-confirmation",
                },
            },
        },
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", ResultStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(
        supervisor,
        "A2ACrewClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Result questions must not call workers")
        ),
    )

    def parse_result_question(*args: Any, **kwargs: Any) -> tuple:
        assert kwargs["current_results"][0]["property_id"] == "p1"
        return (
            {},
            {},
            {
                "intent": "results_question",
                "answer": "Parcel p1 is the saved result.",
                "clear_fields": [],
            },
        )

    monkeypatch.setattr(
        supervisor,
        "_parse_criteria_with_llm",
        parse_result_question,
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-question",
        user_message="Which parcel was saved?",
        user_id="user-1",
    )

    assert result["answered_from_memory"] is True
    assert result["message"] == "Parcel p1 is the saved result."
    assert "clarification" not in result


def test_cancelled_confirmation_restores_previous_result_context(
    monkeypatch,
) -> None:
    from agents.common import trace
    from agents.supervisor import supervisor

    class CancelStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {"session_id": session_id, "user_id": "user-1", "title": "Search"}

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Emitter:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

    previous_criteria = {"state": "texas", "city": "weston", "acres_min": 5}
    pending_criteria = {"state": "texas", "city": "roland", "acres_min": 20}
    CancelStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": previous_criteria,
                "criteria_provenance": {
                    key: "user" for key in previous_criteria
                },
                "shortlist": [_candidate("saved")],
            },
        },
        {
            "role": "assistant",
            "payload": {
                "criteria": pending_criteria,
                "shortlist": [],
                "awaiting_clarification": True,
                "clarification": {
                    "kind": "criteria_confirmation",
                    "pending_criteria": pending_criteria,
                    "pending_provenance": {
                        key: "user" for key in pending_criteria
                    },
                    "original_run_id": "run-confirmation",
                },
            },
        },
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", CancelStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(
        supervisor,
        "_parse_criteria_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Cancellation must not reparse")
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "A2ACrewClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Cancellation must not call workers")
        ),
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-cancel",
        user_message="no",
        user_id="user-1",
    )

    assert result["criteria"] == previous_criteria
    assert result["shortlist"][0]["property_id"] == "saved"
    assert "clarification" not in result


def test_confirmed_unchanged_criteria_returns_cached_results_without_workers(
    monkeypatch,
) -> None:
    from agents.common import trace
    from agents.supervisor import supervisor

    criteria = {"state": "texas", "city": "roland", "acres_min": 2}

    class CacheStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {
                "session_id": session_id,
                "user_id": "user-1",
                "title": "Search",
                "last_criteria_fingerprint": compute_criteria_fingerprint(criteria),
                "last_run_id": "run-cached",
            }

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

        def get_scores_by_run(self, run_id: str) -> list[dict[str, Any]]:
            return [{"parcel_id": "p1", "total_score": 88.0}]

        def get_parcels_by_run(self, run_id: str) -> list[dict[str, Any]]:
            return [
                {
                    "parcel_id": "p1",
                    "location": {"city": "Roland", "state": "TX"},
                    "basic_info": {"price": 250_000, "acres": 2.5},
                }
            ]

        def get_enrichments_by_parcel(
            self,
            run_id: str,
            parcel_id: str,
        ) -> list[dict[str, Any]]:
            return []

        def get_search(self, run_id: str) -> dict[str, Any] | None:
            return {"total_matching": 1}

    class Emitter:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

        def memory_read(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

    CacheStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": criteria,
                "shortlist": [],
                "awaiting_clarification": True,
                "clarification": {
                    "kind": "criteria_confirmation",
                    "pending_criteria": criteria,
                    "pending_provenance": {
                        "state": "user",
                        "city": "user",
                        "acres_min": "user",
                    },
                    "original_run_id": "run-confirmation",
                },
            },
        }
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", CacheStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(
        supervisor,
        "A2ACrewClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Cache hit must not call workers")
        ),
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-cache-check",
        user_message="yes, run it",
        user_id="user-1",
    )

    assert result["cached"] is True
    assert result["shortlist"][0]["property_id"] == "p1"
    assert result["criteria"] == criteria


def test_oversized_scout_result_never_dispatches_expensive_workers(
    monkeypatch,
) -> None:
    from agents.common import trace
    from agents.supervisor import supervisor

    class PipelineStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {"session_id": session_id, "user_id": "user-1", "title": "Search"}

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def insert_search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Emitter:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

        def context(self, *args: Any, **kwargs: Any) -> None:
            return None

        def memory_read(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

        def error(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Client:
        calls: list[str] = []
        contexts: list[dict[str, Any]] = []

        def __init__(self, *args: Any, **kwargs: Any):
            pass

        def send_task(self, **kwargs: Any) -> str:
            self.calls.append(kwargs["target_url"])
            self.contexts.append(kwargs["context"])
            listings = [
                {
                    "property_id": index,
                    "title": f"Parcel {index}",
                    "price": 100_000 + index,
                    "acres": 10,
                    "city": "Mckinney",
                    "county": "Collin County",
                    "state": "TX",
                }
                for index in range(11)
            ]
            return json.dumps(
                {
                    "listings": listings,
                    "total_matching": 11,
                    "search_url": "https://example.test/search",
                }
            )

    confirmed_criteria = {
        "state": "texas",
        "county": "collin",
        "property_types": ["recreational"],
    }
    PipelineStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": confirmed_criteria,
                "shortlist": [],
                "clarification": {
                    "kind": "criteria_confirmation",
                    "round": 0,
                    "pending_criteria": confirmed_criteria,
                    "pending_provenance": {
                        "state": "user",
                        "county": "user",
                        "property_types": "inferred",
                    },
                    "original_run_id": "run-confirmation",
                },
            },
        }
    ]
    Client.calls = []
    Client.contexts = []
    monkeypatch.setattr(memory.store, "PostgresStore", PipelineStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(supervisor, "A2ACrewClient", Client)
    monkeypatch.setattr(
        supervisor,
        "_parse_criteria_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Confirmed criteria must not be reparsed")
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "assess_breadth",
        lambda **kwargs: GateResult(
            sufficient=False,
            question="Select up to 10.",
            common_conditions=["All are in Collin County."],
            recommendations=["Select up to 10 parcels."],
        ),
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-1",
        user_message="yes",
        user_id="user-1",
    )

    assert len(result["candidates"]) == 11
    assert result["shortlist"] == []
    assert len(Client.calls) == 1
    assert ":8002" in Client.calls[0]
    assert Client.contexts[0]["criteria"] == confirmed_criteria
    assert result["criteria_provenance"]["property_types"] == "user"


def test_scout_tool_error_is_reported_not_treated_as_no_matches(
    monkeypatch,
) -> None:
    from agents.common import trace
    from agents.supervisor import supervisor

    class PipelineStore(FakeStore):
        def get_session(self, session_id: str) -> dict[str, Any]:
            return {"session_id": session_id, "user_id": "user-1", "title": "Search"}

        def touch_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def append_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def insert_search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def update_run_status(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Emitter:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

        def context(self, *args: Any, **kwargs: Any) -> None:
            return None

        def memory_read(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

        def error(self, *args: Any, **kwargs: Any) -> None:
            return None

    class Client:
        def __init__(self, *args: Any, **kwargs: Any):
            pass

        def send_task(self, **kwargs: Any) -> str:
            if ":8002" not in kwargs["target_url"]:
                raise AssertionError("Only Scout should run in this scenario")
            return json.dumps(
                {
                    "error": "BlockedError: upstream unavailable",
                    "url": "https://example.test/search",
                }
            )

    confirmed_criteria = {"state": "texas", "county": "collin"}
    PipelineStore.messages = [
        {
            "role": "assistant",
            "payload": {
                "criteria": confirmed_criteria,
                "shortlist": [],
                "clarification": {
                    "kind": "criteria_confirmation",
                    "round": 0,
                    "pending_criteria": confirmed_criteria,
                    "pending_provenance": {
                        "state": "user",
                        "county": "user",
                    },
                    "original_run_id": "run-confirmation",
                },
            },
        }
    ]
    monkeypatch.setattr(memory.store, "PostgresStore", PipelineStore)
    monkeypatch.setattr(trace, "create_trace_emitter", lambda *args: Emitter())
    monkeypatch.setattr(supervisor, "A2ACrewClient", Client)
    monkeypatch.setattr(
        supervisor,
        "_parse_criteria_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Confirmed criteria must not be reparsed")
        ),
    )

    result = supervisor.orchestrate_pipeline(
        session_id="session-1",
        run_id="run-scout-error",
        user_message="yes",
        user_id="user-1",
    )

    assert "Scout search failed" in result["message"]
    assert "BlockedError: upstream unavailable" in result["message"]
    assert "https://example.test/search" in result["message"]
    assert result["shortlist"] == []
