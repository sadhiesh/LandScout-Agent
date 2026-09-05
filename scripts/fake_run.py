#!/usr/bin/env python3
"""Fake-run emitter for testing the debug console.

Replays a synthetic trace timeline so the console can be exercised
without an LLM, Postgres, or Redis.
"""

import asyncio
import httpx
import json
import time
from datetime import datetime, timezone


async def emit_event(client: httpx.AsyncClient, run_id: str, agent: str, kind: str, summary: str, data: dict | None = None):
    """Emit a single trace event to the API."""
    event = {
        "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "kind": kind,
        "summary": summary,
        "data": data,
    }
    
    try:
        response = await client.post(
            "http://localhost:8000/internal/trace",
            json=event,
            timeout=2.0
        )
        if response.is_success:
            print(f"✓ [{agent}] {kind}: {summary}")
        else:
            print(f"✗ Failed to emit {kind}: {response.status_code}")
    except Exception as e:
        print(f"✗ Error emitting {kind}: {e}")


async def run_fake_pipeline(run_id: str):
    """Replay a synthetic agent pipeline execution."""
    print(f"\n🚀 Starting fake pipeline run: {run_id}\n")
    
    async with httpx.AsyncClient() as client:
        # Supervisor starts
        await emit_event(
            client, run_id, "supervisor", "route",
            "Pipeline started", {"user_message": "Find land in Texas under $500k"}
        )
        await asyncio.sleep(0.5)
        
        # Memory check
        await emit_event(
            client, run_id, "supervisor", "memory_read",
            "Memory: criteria_cache_check",
            {"operation": "criteria_cache_check", "result": "miss - will run pipeline"}
        )
        await asyncio.sleep(0.5)
        
        # Context for Scout
        await emit_event(
            client, run_id, "supervisor", "context",
            "Context: ~150 tokens",
            {"payload_keys": ["criteria", "run_id"], "estimated_tokens": 150}
        )
        await asyncio.sleep(0.5)
        
        # A2A send to Scout
        await emit_event(
            client, run_id, "supervisor", "a2a_send",
            "→ scout: Search for land parcels matching criteria",
            {"target": "scout", "task": "Search for land parcels"}
        )
        await asyncio.sleep(0.5)
        
        # Scout starts
        await emit_event(
            client, run_id, "scout", "subagent_start",
            "Starting scout",
            {"subagent": "scout", "task": "Search for land parcels"}
        )
        await asyncio.sleep(0.5)
        
        # Scout tool call
        await emit_event(
            client, run_id, "scout", "tool_call",
            "🛠 landwatch_search",
            {"tool": "landwatch_search", "args": {"state": "TX", "max_price": 500000}}
        )
        await asyncio.sleep(1.5)
        
        # Scout tool result
        await emit_event(
            client, run_id, "scout", "tool_result",
            "✓ landwatch_search",
            {
                "tool": "landwatch_search",
                "result": "Found 15 parcels",
                "duration_ms": 1450
            }
        )
        await asyncio.sleep(0.5)
        
        # Scout finishes
        await emit_event(
            client, run_id, "scout", "subagent_finish",
            "Finished scout (2100ms, 1243 chars)",
            {"subagent": "scout", "duration_ms": 2100, "result_size": 1243}
        )
        await asyncio.sleep(0.5)
        
        # Context for Enricher
        await emit_event(
            client, run_id, "supervisor", "context",
            "Context: ~2800 tokens",
            {"payload_keys": ["parcels", "run_id"], "estimated_tokens": 2800}
        )
        await asyncio.sleep(0.5)
        
        # A2A send to Enricher
        await emit_event(
            client, run_id, "supervisor", "a2a_send",
            "→ enricher: Enrich parcels",
            {"target": "enricher", "task": "Enrich 15 parcels"}
        )
        await asyncio.sleep(0.5)
        
        # Enricher starts
        await emit_event(
            client, run_id, "enricher", "subagent_start",
            "Starting enricher",
            {"subagent": "enricher", "task": "Enrich 15 parcels"}
        )
        await asyncio.sleep(2.0)
        
        # Enricher finishes
        await emit_event(
            client, run_id, "enricher", "subagent_finish",
            "Finished enricher (3200ms, 5421 chars)",
            {"subagent": "enricher", "duration_ms": 3200, "result_size": 5421}
        )
        await asyncio.sleep(0.5)
        
        # Context for Scorer
        await emit_event(
            client, run_id, "supervisor", "context",
            "Context: ~5200 tokens",
            {"payload_keys": ["enriched_parcels", "criteria", "run_id"], "estimated_tokens": 5200}
        )
        await asyncio.sleep(0.5)
        
        # A2A send to Scorer
        await emit_event(
            client, run_id, "supervisor", "a2a_send",
            "→ scorer: Score parcels",
            {"target": "scorer", "task": "Score 15 parcels"}
        )
        await asyncio.sleep(0.5)
        
        # Scorer starts
        await emit_event(
            client, run_id, "scorer", "subagent_start",
            "Starting scorer",
            {"subagent": "scorer", "task": "Score 15 parcels"}
        )
        await asyncio.sleep(1.5)
        
        # Scorer finishes
        await emit_event(
            client, run_id, "scorer", "subagent_finish",
            "Finished scorer (2800ms, 6832 chars)",
            {"subagent": "scorer", "duration_ms": 2800, "result_size": 6832}
        )
        await asyncio.sleep(0.5)
        
        # Memory write
        await emit_event(
            client, run_id, "supervisor", "memory_write",
            "Persisted 15 parcels_scores_enrichments",
            {"operation": "parcels_scores_enrichments", "count": 15}
        )
        await asyncio.sleep(0.5)
        
        # Pipeline complete
        await emit_event(
            client, run_id, "supervisor", "route",
            "✓ Pipeline completed: 15 parcels scored",
            {"total_found": 15, "shortlist_size": 10}
        )
        
    print(f"\n✅ Fake pipeline completed\n")


if __name__ == "__main__":
    import sys
    
    run_id = sys.argv[1] if len(sys.argv) > 1 else f"fake-{int(time.time())}"
    
    print("=" * 60)
    print("Fake Run Emitter - LandScout Debug Console Test")
    print("=" * 60)
    print(f"\n📍 API: http://localhost:8000/internal/trace")
    print(f"📍 Console: http://localhost:8000 or http://localhost:5173")
    print(f"📍 SSE Stream: http://localhost:8000/events/{run_id}")
    
    try:
        asyncio.run(run_fake_pipeline(run_id))
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        sys.exit(1)
