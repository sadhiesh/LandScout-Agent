"""Debug endpoints — read-only views over audit logs and memory."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from memory.store import PostgresStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Get session details."""
    with PostgresStore() as pg:
        session = pg.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return session


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Get run details."""
    with PostgresStore() as pg:
        run = pg.get_run(run_id)
        
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        
        return run


@router.get("/runs/{run_id}/parcels")
async def get_run_parcels(run_id: str) -> list[dict[str, Any]]:
    """Get all parcels for a run."""
    with PostgresStore() as pg:
        parcels = pg.get_parcels_by_run(run_id)
        return parcels


@router.get("/runs/{run_id}/scores")
async def get_run_scores(run_id: str) -> list[dict[str, Any]]:
    """Get all scores for a run, ordered by score descending."""
    with PostgresStore() as pg:
        scores = pg.get_scores_by_run(run_id)
        return scores


@router.get("/runs/{run_id}/trace")
async def get_run_trace(run_id: str) -> list[dict[str, Any]]:
    """Get all trace events for a run, ordered by timestamp."""
    with PostgresStore() as pg:
        events = pg.get_trace_events_by_run(run_id)
        return events


@router.get("/parcels/{parcel_id}")
async def get_parcel_enrichments(parcel_id: str) -> dict[str, Any]:
    """Get all enrichments for a parcel."""
    with PostgresStore() as pg:
        enrichments = pg.get_enrichments_by_parcel(parcel_id)
        
        # Group by source
        enriched_data = {}
        for enr in enrichments:
            enriched_data[enr["source"]] = enr["data"]
        
        return {
            "parcel_id": parcel_id,
            "enrichments": enriched_data,
        }


@router.get("/tools")
async def get_tools_catalog() -> dict[str, Any]:
    """Get the tool catalog (derived from FILTER_CATALOG and enrichment REGISTRY).
    
    Never restates the tool vocabulary — derives it from the source of truth.
    """
    try:
        # Import landwatch catalog
        from landwatch.tools import FILTER_CATALOG, TOOL_DESCRIPTION, TOOL_NAME
        
        # Import enrichment registry
        from tools.enrichment.registry import REGISTRY, get_enabled_enrichers
        
        landwatch_tool = {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "filters": FILTER_CATALOG,
        }
        
        enrichers = [
            {
                "name": e.name,
                "description": e.description,
                "enabled": e.enabled,
            }
            for e in REGISTRY
        ]
        
        return {
            "landwatch_search": landwatch_tool,
            "enrichers": enrichers,
        }
    except Exception as e:
        logger.error(f"Failed to build tool catalog: {e}")
        return {"error": str(e)}


@router.get("/agents")
async def get_agents() -> list[dict[str, Any]]:
    """Get agent cards from each AGENT.md."""
    agents = [
        {
            "name": "supervisor",
            "port": 8001,
            "role": "Orchestrator",
            "description": "Parses intent, manages memory, routes to workers",
            "tools": [],
        },
        {
            "name": "scout",
            "port": 8002,
            "role": "Search",
            "description": "Criteria → parcel search",
            "tools": ["landwatch_search"],
        },
        {
            "name": "enricher",
            "port": 8003,
            "role": "Enrichment",
            "description": "Per-parcel fact gathering",
            "tools": ["landwatch_detail", "county_comps"],
        },
        {
            "name": "scorer",
            "port": 8004,
            "role": "Scoring",
            "description": "Deterministic scoring + rationale generation",
            "tools": ["score_parcel"],
        },
    ]
    return agents


@router.get("/runs/{run_id}/context")
async def get_run_context(run_id: str) -> dict[str, Any]:
    """Get all context events for a run."""
    with PostgresStore() as pg:
        events = pg.get_trace_events_by_run(run_id)
        
        # Filter to context events only
        context_events = [e for e in events if e.get("kind") == "context"]
        
        return {
            "run_id": run_id,
            "context_events": context_events,
        }
