"""Offline contract tests for chat persistence and narrowing payloads."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import memory.store
from api import chat as chat_module


class FakeStore:
    writes: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeStore":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "run_id": run_id,
            "payload": payload,
        }
        self.writes.append(row)
        return row


class FakeA2AClient:
    last_context: dict[str, Any] = {}

    def __init__(self, source_agent: str):
        self.source_agent = source_agent

    def send_task(self, **kwargs: Any) -> str:
        type(self).last_context = kwargs["context"]
        return json.dumps(
            {
                "message": "LandWatch shows 20 matches. Choose one more filter.",
                "shortlist": [],
                "refinement_options": [
                    {"id": "city:anna", "section": "City", "label": "Anna", "count": 8}
                ],
                "narrowing_analysis": {
                    "common_conditions": ["Location filters can cut the result set sharply."],
                    "recommendations": ["City: Anna (8 matches)"],
                },
                "criteria": {"county": "collin"},
                "total_matching": 20,
                "awaiting_clarification": True,
                "clarification": {
                    "kind": "facet_narrowing",
                    "refinement_options": [
                        {"id": "city:anna", "section": "City", "label": "Anna", "count": 8}
                    ],
                },
                "journey_steps": [
                    {"type": "searched", "message": "Found broad results.", "details": {}}
                ],
            }
        )


def test_chat_persists_one_final_assistant_narrowing_message(monkeypatch) -> None:
    FakeStore.writes = []
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)
    monkeypatch.setattr(chat_module, "A2ACrewClient", FakeA2AClient)

    request = SimpleNamespace(state=SimpleNamespace(run_id="run-1"))
    payload = chat_module.ChatRequestModel(
        session_id="session-1",
        message="Analyze these two.",
        user_id="user-1",
        selected_parcel_ids=["p1", "p2"],
    )

    asyncio.run(chat_module.chat(request, payload))

    assistant_writes = [row for row in FakeStore.writes if row["role"] == "assistant"]
    final_writes = [
        row
        for row in assistant_writes
        if not (row["payload"] or {}).get("journey_step")
    ]
    assert len(assistant_writes) == 2
    assert len(final_writes) == 1
    persisted = final_writes[0]["payload"]
    assert persisted["refinement_options"][0]["label"] == "Anna"
    assert persisted["narrowing_analysis"]["recommendations"]
    assert persisted["candidate_limit"] == chat_module.CANDIDATE_LIMIT
    assert persisted["awaiting_clarification"] is True
    assert persisted["clarification"]["kind"] == "facet_narrowing"
    assert FakeA2AClient.last_context["selected_parcel_ids"] == ["p1", "p2"]


def test_chat_request_rejects_more_than_ten_selected_ids() -> None:
    with pytest.raises(ValidationError):
        chat_module.ChatRequestModel(
            session_id="session-1",
            message="Analyze these.",
            selected_parcel_ids=[str(index) for index in range(11)],
        )


def test_chat_forwards_selected_refinement_id(monkeypatch) -> None:
    FakeStore.writes = []
    monkeypatch.setattr(memory.store, "PostgresStore", FakeStore)
    monkeypatch.setattr(chat_module, "A2ACrewClient", FakeA2AClient)

    request = SimpleNamespace(state=SimpleNamespace(run_id="run-2"))
    payload = chat_module.ChatRequestModel(
        session_id="session-1",
        message="Apply City: Anna",
        selected_refinement_id="city:anna",
    )

    asyncio.run(chat_module.chat(request, payload))

    assert FakeA2AClient.last_context["selected_refinement_id"] == "city:anna"
