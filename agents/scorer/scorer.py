"""Scorer Agent — parcel ranking and rationale generation.

Port 8004. Ranks enriched parcels using deterministic scoring, then uses
LLM to write rationales based on the score breakdowns.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from crewai import Agent, Crew, Task
from fastapi import FastAPI
import uvicorn

from agents.common import (
    SCORER_PORT,
    build_llm,
    create_trace_emitter,
)
from agents.common.a2a_server import TaskRequest, TaskResponse
from agents.common.middleware import add_standard_cors, add_health_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def score_parcels_direct(
    parcels: list[dict[str, Any]], criteria: dict[str, Any], run_id: str = "unknown"
) -> list[dict[str, Any]]:
    """Score parcels using the deterministic scoring system.
    
    This computes scores and breakdowns deterministically.
    
    Args:
        parcels: List of enriched parcel dicts
        criteria: Search/investment criteria
        run_id: Run identifier for logging
        
    Returns:
        List of parcels with scores and breakdowns added
    """
    from tools.scoring import score_parcel
    
    scored_parcels = []
    
    for parcel in parcels:
        try:
            enrichment = parcel.get("enrichment", {})
            result = score_parcel(parcel, criteria, enrichment)
            
            # Add score data to parcel
            scored_parcel = parcel.copy()
            scored_parcel["score"] = result.total_score
            scored_parcel["score_breakdown"] = result.to_dict()
            # Note: rationale will be added by LLM pass
            scored_parcels.append(scored_parcel)
            
            logger.info(
                f"[{run_id}] Scored parcel {parcel.get('property_id')}: {result.total_score:.1f}"
            )
            
        except Exception as e:
            logger.error(
                f"[{run_id}] Failed to score parcel {parcel.get('property_id')}: {e}",
                exc_info=True,
            )
            # Add a failed score
            scored_parcel = parcel.copy()
            scored_parcel["score"] = 0.0
            scored_parcel["score_breakdown"] = {
                "error": str(e),
                "skipped_dimensions": [],
            }
            scored_parcels.append(scored_parcel)
    
    # Sort by score descending
    scored_parcels.sort(key=lambda p: p.get("score", 0), reverse=True)
    
    return scored_parcels


def create_rationale_agent(provider: str | None = None, model: str | None = None) -> Agent:
    """Create agent that writes rationales from score breakdowns.
    
    Args:
        provider: Optional LLM provider override
        model: Optional LLM model override
    """
    llm = build_llm(provider=provider, model=model)
    
    return Agent(
        role="Investment Rationale Writer",
        goal=(
            "Write clear, defensible rationales based on deterministic score breakdowns "
            "and flag external considerations worth checking"
        ),
        backstory=(
            "You translate numerical score breakdowns into clear, readable English "
            "that explains why each parcel scored as it did. You cite specific "
            "numbers from the breakdown (e.g., '$4,100/acre vs county median $6,800') "
            "rather than making generic claims. The scoring math is already done - "
            "your job is to make it understandable. If data is thin, you say so "
            "rather than inventing support for a ranking.\n\n"
            "You also flag 2-3 external considerations - things worth checking that "
            "are not in the score breakdown. Phrase each as a question or check rather "
            "than an assertion. Never restate a fact already in the breakdown, and "
            "never mention disabled enrichers (flood, soil, zoning) as if they were run."
        ),
        tools=[],
        llm=llm,
        verbose=True,
    )


async def write_rationales_with_llm(
    scored_parcels: list[dict[str, Any]],
    criteria: dict[str, Any],
    run_id: str = "unknown",
    provider: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Use LLM to write rationales from deterministic breakdowns.
    
    Args:
        scored_parcels: Parcels with scores and breakdowns
        criteria: Search criteria
        run_id: Run identifier for logging
        provider: Optional LLM provider override
        model: Optional LLM model override
    """
    agent = create_rationale_agent(provider=provider, model=model)
    
    # Build a task asking the agent to write rationales
    # We'll do this in batch - send top N parcels
    top_parcels = scored_parcels[:20]  # Only write rationales for top 20
    
    # Format breakdowns for the LLM
    breakdown_summaries = []
    for idx, parcel in enumerate(top_parcels):
        prop_id = parcel.get("property_id")
        score = parcel.get("score", 0)
        breakdown = parcel.get("score_breakdown", {})
        
        summary = f"Parcel {prop_id} (Score: {score:.1f}/100):\n"
        
        dims = breakdown.get("dimensions", {})
        for dim_name, dim_data in dims.items():
            if isinstance(dim_data, dict):
                explanation = dim_data.get("explanation", "")
                weighted = dim_data.get("weighted_score", 0)
                summary += f"  - {dim_name}: {weighted:.1f} points - {explanation}\n"
        
        breakdown_summaries.append({
            "property_id": prop_id,
            "index": idx,
            "summary": summary
        })
    
    # Create a task for the agent
    task = Task(
        description=(
            f"For each parcel, write:\n"
            f"1. A 1-2 sentence rationale based on its score breakdown (cite specific numbers)\n"
            f"2. A list of 2-3 external considerations - things worth checking that are NOT "
            f"in the breakdown. Phrase each as a question or check, never as an assertion.\n\n"
            f"Here are the breakdowns:\n\n" +
            "\n".join(bs["summary"] for bs in breakdown_summaries) +
            f"\n\nCriteria: {json.dumps(criteria, indent=2)}\n\n"
            f'Return JSON: [{{"property_id": 123, "rationale": "...", "considerations": ["...", "..."]}}, ...]'
        ),
        expected_output="JSON array with property_id, rationale, and considerations",
        agent=agent,
    )
    
    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=False,
    )
    
    try:
        result = await crew.kickoff_async()
        
        # Extract JSON from result
        from agents.common.json_utils import extract_json
        rationales_data = extract_json(str(result))
        
        # Match rationales and considerations back to parcels
        rationale_map = {}
        considerations_map = {}
        
        for item in rationales_data:
            if isinstance(item, dict) and "property_id" in item:
                prop_id = item["property_id"]
                if "rationale" in item:
                    rationale_map[prop_id] = item["rationale"]
                # Default considerations to empty list if missing or invalid
                considerations = item.get("considerations", [])
                if isinstance(considerations, list):
                    considerations_map[prop_id] = considerations
                else:
                    considerations_map[prop_id] = []
        
        # Add rationales and considerations to scored parcels
        for parcel in scored_parcels:
            prop_id = parcel.get("property_id")
            if prop_id in rationale_map:
                parcel["rationale"] = rationale_map[prop_id]
                parcel["considerations"] = considerations_map.get(prop_id, [])
            else:
                # Fallback: use the top dimension's explanation
                breakdown = parcel.get("score_breakdown", {})
                dims = breakdown.get("dimensions", {})
                if dims:
                    first_dim = next(iter(dims.values()), {})
                    parcel["rationale"] = first_dim.get("explanation", "")
                else:
                    parcel["rationale"] = ""
                parcel["considerations"] = []
        
        return scored_parcels
        
    except Exception as e:
        logger.error(f"[{run_id}] LLM rationale generation failed: {e}", exc_info=True)
        # Fallback: use dimension explanations, no considerations
        for parcel in scored_parcels:
            breakdown = parcel.get("score_breakdown", {})
            dims = breakdown.get("dimensions", {})
            if dims:
                first_dim = next(iter(dims.values()), {})
                parcel["rationale"] = first_dim.get("explanation", "")
            else:
                parcel["rationale"] = ""
            parcel["considerations"] = []
        
        return scored_parcels


def main() -> None:
    """Run the Scorer agent as an A2A server."""
    logger.info("Starting Scorer agent (deterministic + LLM rationales)...")
    
    app = FastAPI(title="Scorer A2A Service")
    
    # Add standard middleware and health check
    add_standard_cors(app)
    add_health_check(app, "scorer")
    
    @app.post("/message", response_model=TaskResponse)
    async def handle_message(request: TaskRequest) -> TaskResponse:
        """Handle incoming A2A task request."""
        try:
            # Create trace emitter for this run
            run_id = request.run_id
            logger.info(f"[{run_id}] Received task: {request.task_description[:100]}")
            emitter = create_trace_emitter(run_id, "scorer")
            
            # Emit a2a_recv event
            emitter.emit(
                "a2a_recv",
                f"← Task: {request.task_description[:80]}",
                {
                    "task_id": request.task_id,
                    "full_description": request.task_description,
                    "context": request.context,
                },
            )
            
            # Emit subagent_start event
            emitter.emit(
                "subagent_start",
                "Starting scorer",
                {"subagent": "scorer", "task": request.task_description[:200]}
            )
            
            import time
            start_time = time.time()
            
            # Extract context
            context = request.context or {}
            enriched_parcels = context.get("enriched_parcels", [])
            criteria = context.get("criteria", {})
            llm_provider = context.get("llm_provider")
            llm_model = context.get("llm_model")
            
            if not enriched_parcels:
                raise ValueError("No enriched_parcels provided in context")
            
            # Step 1: Deterministic scoring
            emitter.emit("tool_call", "🛠 deterministic_scoring", {"tool": "score_parcel", "count": len(enriched_parcels)})
            
            score_start = time.time()
            scored_parcels = score_parcels_direct(enriched_parcels, criteria, run_id)
            score_duration = (time.time() - score_start) * 1000
            
            emitter.emit(
                "tool_result",
                f"✓ deterministic_scoring: {len(scored_parcels)} parcels scored",
                {"tool": "score_parcel", "duration_ms": score_duration, "count": len(scored_parcels)}
            )
            
            # Step 2: LLM rationale generation
            emitter.emit("thought", f"Writing rationales for top {min(20, len(scored_parcels))} parcels", {})
            
            rationale_start = time.time()
            scored_parcels = await write_rationales_with_llm(
                scored_parcels, criteria, run_id, provider=llm_provider, model=llm_model
            )
            rationale_duration = (time.time() - rationale_start) * 1000
            
            emitter.emit("thought", f"Rationales written in {rationale_duration:.0f}ms", {"duration_ms": rationale_duration})
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Build result
            result = {
                "scored_parcels": scored_parcels,
            }
            result_json = json.dumps(result, default=str)
            
            logger.info(
                f"[{run_id}] Scored and wrote rationales for {len(scored_parcels)} parcels"
            )
            
            # Emit subagent_finish event
            emitter.emit(
                "subagent_finish",
                f"Finished scorer ({duration_ms:.0f}ms, {len(result_json)} chars)",
                {"subagent": "scorer", "duration_ms": duration_ms, "result_size": len(result_json)}
            )
            
            # Emit route event for completion
            emitter.emit(
                "route",
                f"✓ Scoring completed: {len(scored_parcels)} parcels ranked",
                {"task_id": request.task_id, "parcel_count": len(scored_parcels)},
            )
            
            # Close emitter
            emitter.close()
            
            return TaskResponse(
                task_id=request.task_id,
                status="completed",
                result=result_json,
            )
            
        except Exception as e:
            run_id = request.run_id
            logger.error(f"[{run_id}] Task failed: {e}", exc_info=True)
            
            try:
                emitter = create_trace_emitter(run_id, "scorer")
                emitter.emit(
                    "error",
                    f"✗ Task failed: {type(e).__name__}",
                    {"task_id": request.task_id, "error": str(e)},
                )
                emitter.close()
            except Exception:
                pass  # Don't let trace emission failure prevent error response
            
            return TaskResponse(
                task_id=request.task_id,
                status="failed",
                result=None,
                error=str(e),
            )
    
    # Run the server
    logger.info(f"Starting Scorer A2A server on port {SCORER_PORT}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=SCORER_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
