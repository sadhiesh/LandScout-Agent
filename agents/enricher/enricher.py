"""Enricher Agent — per-parcel fact gathering.

Port 8003. Adds the facts that determine buy quality to each candidate parcel
using the pluggable enrichment registry. Deterministic execution - no LLM.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI
import uvicorn

from agents.common import (
    ENRICHER_PORT,
    create_trace_emitter,
)
from agents.common.a2a_server import TaskRequest, TaskResponse
from agents.common.middleware import add_standard_cors, add_health_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def enrich_parcels_direct(
    parcels: list[dict[str, Any]],
    progress_callback: Any = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Enrich parcels using the registry directly.
    
    Args:
        parcels: List of parcel dicts to enrich
        progress_callback: Optional callback for trace events
        
    Returns:
        Tuple of (enriched_parcels, sources_used, sources_failed)
    """
    from tools.enrichment import run_enrichment
    
    enriched_parcels = []
    all_sources_used: set[str] = set()
    all_sources_failed: set[str] = set()
    
    for parcel in parcels:
        enriched_data, sources_used, sources_failed = run_enrichment(
            parcel, progress_callback=progress_callback
        )
        
        # Merge enrichment onto parcel
        parcel_with_enrichment = parcel.copy()
        parcel_with_enrichment["enrichment"] = enriched_data
        enriched_parcels.append(parcel_with_enrichment)
        
        all_sources_used.update(sources_used)
        all_sources_failed.update(sources_failed)
    
    return (
        enriched_parcels,
        sorted(all_sources_used),
        sorted(all_sources_failed),
    )


def main() -> None:
    """Run the Enricher agent as an A2A server with deterministic execution."""
    logger.info("Starting Enricher agent (deterministic)...")
    
    app = FastAPI(title="Enricher A2A Service")
    
    # Add standard middleware and health check
    add_standard_cors(app)
    add_health_check(app, "enricher")
    
    @app.post("/message", response_model=TaskResponse)
    async def handle_message(request: TaskRequest) -> TaskResponse:
        """Handle incoming A2A task request with deterministic enrichment."""
        try:
            # Create trace emitter for this run
            run_id = request.run_id
            logger.info(f"[{run_id}] Received task: {request.task_description[:100]}")
            emitter = create_trace_emitter(run_id, "enricher")
            
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
                "Starting enricher",
                {"subagent": "enricher", "task": request.task_description[:200]}
            )
            
            import time
            start_time = time.time()
            
            # Extract parcels from context
            context = request.context or {}
            parcels = context.get("parcels", [])
            
            if not parcels:
                raise ValueError("No parcels provided in context")
            
            # Run deterministic enrichment with trace callback
            def trace_callback(kind: str, summary: str, data: dict | None) -> None:
                emitter.emit(kind, summary, data)
            
            enriched_parcels, sources_used, sources_failed = enrich_parcels_direct(
                parcels,
                progress_callback=trace_callback,
            )
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Build result JSON
            result = {
                "enriched_parcels": enriched_parcels,
                "sources_used": sources_used,
                "sources_failed": sources_failed,
            }
            result_json = json.dumps(result, default=str)
            
            logger.info(
                f"[{run_id}] Enriched {len(enriched_parcels)} parcels: "
                f"{len(sources_used)} sources used, {len(sources_failed)} failed"
            )
            
            # Emit subagent_finish event
            emitter.emit(
                "subagent_finish",
                f"Finished enricher ({duration_ms:.0f}ms, {len(result_json)} chars)",
                {"subagent": "enricher", "duration_ms": duration_ms, "result_size": len(result_json)}
            )
            
            # Emit route event for completion
            emitter.emit(
                "route",
                f"✓ Enrichment completed: {len(sources_used)} sources, {len(sources_failed)} failed",
                {"task_id": request.task_id, "sources_used": sources_used, "sources_failed": sources_failed},
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
                emitter = create_trace_emitter(run_id, "enricher")
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
    logger.info(f"Starting Enricher A2A server on port {ENRICHER_PORT}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=ENRICHER_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
