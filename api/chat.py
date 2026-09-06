"""Chat endpoint — invokes Supervisor and streams responses."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from agents.common import SUPERVISOR_PORT, make_agent_url, A2A_SUPERVISOR_TIMEOUT, SSE_HEARTBEAT_INTERVAL
from agents.common.a2a_client import A2ACrewClient
from memory.schemas import ChatRequest, ChatResponse
from memory.store import RedisStore
from tools.scoring import get_shortlist_size

logger = logging.getLogger(__name__)

router = APIRouter()
CANDIDATE_LIMIT = get_shortlist_size()


class ChatRequestModel(BaseModel):
    """Chat request model."""
    
    session_id: str
    message: str
    user_id: str | None = None  # Optional: if already identified
    skip_cache: bool = False  # Bypass criteria cache for development/testing
    selected_parcel_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=CANDIDATE_LIMIT,
        description="Property IDs selected from the pending Scout candidate set.",
    )
    selected_refinement_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Facet refinement option selected from the latest pending narrowing step.",
    )
    selected_refinement_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description=(
            "Multiple facet refinement options selected from the latest pending "
            "narrowing step's facet groups, applied together in one turn. Takes "
            "precedence over selected_refinement_id when both are set."
        ),
    )
    llm_provider: str | None = None  # LLM provider (gateway, openrouter, etc.)
    llm_model: str | None = None  # Model identifier for the selected provider
    
    @property
    def validated_llm_selection(self):
        """Validate and resolve the LLM provider/model selection.
        
        Returns:
            Tuple of (provider, model) or (None, None) for defaults
            
        Raises:
            ValueError: If the provider/model pair is not in the catalog
        """
        if self.llm_provider is None and self.llm_model is None:
            return (None, None)
        
        # Import here to avoid circular dependency
        from agents.common.model_catalog import resolve_selection, UnknownModelError
        
        try:
            selection = resolve_selection(self.llm_provider, self.llm_model)
            return (selection.provider, selection.model)
        except UnknownModelError as e:
            raise ValueError(str(e)) from e


@router.post("/chat", response_model=dict)
async def chat(request: Request, payload: ChatRequestModel) -> dict[str, Any]:
    """Process user message and return land parcel recommendations.
    
    Invokes the Supervisor agent which orchestrates Scout, Enricher, and Scorer.
    """
    run_id = request.state.run_id
    session_id = payload.session_id
    user_message = payload.message
    user_id = payload.user_id
    skip_cache = payload.skip_cache
    selected_parcel_ids = payload.selected_parcel_ids
    selected_refinement_id = payload.selected_refinement_id
    selected_refinement_ids = payload.selected_refinement_ids
    
    # Validate LLM provider/model selection
    try:
        llm_provider, llm_model = payload.validated_llm_selection
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    logger.info(
        f"[{run_id}] Chat request from session {session_id}, user {user_id}: {user_message[:100]}"
    )
    
    try:
        # Invoke Supervisor via A2A (run off the event loop to avoid blocking /internal/trace and SSE)
        a2a_client = A2ACrewClient("api")
        
        supervisor_response = await asyncio.to_thread(
            a2a_client.send_task,
            target_url=make_agent_url(SUPERVISOR_PORT),
            run_id=run_id,
            task_description=(
                f"User message: {user_message}\n\n"
                f"Parse criteria from the message, check memory for cached results, and if needed, "
                f"orchestrate Scout → Enricher → Scorer to produce a ranked shortlist. "
                f"Return JSON with shortlist, criteria, and metadata."
            ),
            expected_output="JSON with shortlist of scored parcels",
            context={
                "session_id": session_id,
                "run_id": run_id,
                "user_message": user_message,
                "user_id": user_id,
                "skip_cache": skip_cache,
                "selected_parcel_ids": selected_parcel_ids,
                "selected_refinement_id": selected_refinement_id,
                "selected_refinement_ids": selected_refinement_ids,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
            timeout=A2A_SUPERVISOR_TIMEOUT,
        )
        
        result = json.loads(supervisor_response)
        
        logger.info(
            f"[{run_id}] Supervisor completed: "
            f"{len(result.get('shortlist', []))} parcels"
        )
        
        # Extract journey steps and persist them as chat messages
        from memory.store import PostgresStore
        journey_steps = result.get("journey_steps", [])
        
        with PostgresStore() as pg:
            # Emit each journey step as a separate assistant message
            for step in journey_steps:
                # Format step message with appropriate emoji/formatting
                step_msg = step["message"]
                step_type = step.get("type", "status")
                
                # Store journey step as assistant message
                pg.append_message(
                    session_id,
                    "assistant",
                    step_msg,
                    run_id=run_id,
                    payload={
                        "journey_step": True,
                        "step_type": step_type,
                        "step_details": step.get("details", {})
                    }
                )
            
            # Finally, persist the summary message with shortlist
            assistant_msg = result.get("message", "Search complete")
            message_payload = {
                "shortlist": result.get("shortlist", []),
                "candidates": result.get("candidates", []),
                "candidate_analysis": result.get("candidate_analysis"),
                "refinement_options": result.get("refinement_options", []),
                "narrowing_analysis": result.get("narrowing_analysis"),
                "candidate_limit": result.get("candidate_limit", CANDIDATE_LIMIT),
                "total_matching": result.get("total_matching", 0),
                "criteria": result.get("criteria", {}),
                "criteria_provenance": result.get("criteria_provenance")
                or (result.get("clarification") or {}).get("pending_provenance")
                or {},
                "awaiting_clarification": result.get(
                    "awaiting_clarification", False
                ),
            }
            
            # Include error field if Scout failed, so session context loader skips this turn
            if result.get("error"):
                message_payload["error"] = result["error"]
            
            # A clarifying question carries the criteria it is waiting on, so
            # the next turn can merge the user's answer onto them instead of
            # starting over. See agents/supervisor/criteria_gate.py.
            if result.get("clarification"):
                message_payload["clarification"] = result["clarification"]
            
            pg.append_message(
                session_id,
                "assistant",
                assistant_msg,
                run_id=run_id,
                payload=message_payload
            )
        
        return {
            "run_id": run_id,
            "session_id": session_id,
            "result": result,
        }
        
    except Exception as e:
        logger.error(f"[{run_id}] Chat request failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "run_id": run_id},
        )


@router.get("/events/{run_id}")
async def events(run_id: str):
    """SSE stream of trace events for a run.
    
    Subscribes to the in-process event bus. Replays buffered events,
    then streams new events as they arrive with periodic heartbeats.
    """
    from api.events import get_event_bus
    
    async def event_generator():
        """Generate SSE events from the event bus."""
        bus = get_event_bus()
        
        # Subscribe and get replay buffer + live queue
        replay_buffer, queue = await bus.subscribe(run_id)
        
        try:
            # First, replay all buffered events
            for event in replay_buffer:
                yield f"data: {json.dumps(event)}\n\n"
            
            # Then stream new events with heartbeat
            while True:
                try:
                    # Wait for next event with timeout for heartbeat
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat comment to keep connection alive
                    yield ": heartbeat\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            logger.info(f"SSE client disconnected for run {run_id}")
        finally:
            await bus.unsubscribe(run_id, queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
