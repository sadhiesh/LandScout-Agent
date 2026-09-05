"""In-process event bus for trace events.

Provides an infra-free transport for real-time agent debugging. Workers POST
to /internal/trace, the bus fans out to SSE subscribers, and best-effort
side writes to Postgres/Redis when available.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TraceEventModel(BaseModel):
    """Trace event for the bus (matches memory.schemas.TraceEvent)."""
    
    run_id: str
    ts: datetime
    agent: str
    kind: str
    summary: str
    data: dict[str, Any] | None = None


class EventBus:
    """In-process event bus with replay buffer and fan-out to SSE subscribers.
    
    Each run_id gets:
    - A bounded deque (ring buffer) for late-subscriber replay
    - A set of asyncio.Queue instances, one per active SSE connection
    """
    
    def __init__(self, buffer_size: int = 500):
        """Initialize the event bus.
        
        Args:
            buffer_size: Max events per run_id to buffer for replay
        """
        self.buffer_size = buffer_size
        # run_id -> deque of events (ring buffer)
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        # run_id -> set of asyncio.Queue (active subscribers)
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
    
    async def publish(self, event: dict[str, Any]) -> None:
        """Publish an event to the bus.
        
        Adds to the replay buffer and fans out to all active subscribers.
        
        Args:
            event: Event dict matching TraceEventModel
        """
        run_id = event.get("run_id")
        if not run_id:
            logger.warning("Event missing run_id, skipping")
            return
        
        async with self._lock:
            # Add to replay buffer (bounded)
            if run_id not in self._buffers:
                self._buffers[run_id] = deque(maxlen=self.buffer_size)
            self._buffers[run_id].append(event)
            
            # Fan out to all subscribers
            if run_id in self._subscribers:
                dead_queues = set()
                for queue in self._subscribers[run_id]:
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(f"Subscriber queue full for run {run_id}, dropping event")
                    except Exception as e:
                        logger.error(f"Failed to publish to subscriber: {e}")
                        dead_queues.add(queue)
                
                # Clean up dead queues
                for queue in dead_queues:
                    self._subscribers[run_id].discard(queue)
    
    async def subscribe(self, run_id: str, max_queue_size: int = 100) -> tuple[list[dict[str, Any]], asyncio.Queue]:
        """Subscribe to events for a run.
        
        Returns:
            - Replay buffer (all past events)
            - asyncio.Queue for new events
        """
        async with self._lock:
            # Get replay buffer
            replay = list(self._buffers.get(run_id, []))
            
            # Create subscriber queue
            queue = asyncio.Queue(maxsize=max_queue_size)
            
            # Register subscriber
            if run_id not in self._subscribers:
                self._subscribers[run_id] = set()
            self._subscribers[run_id].add(queue)
            
            return replay, queue
    
    async def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from events for a run."""
        async with self._lock:
            if run_id in self._subscribers:
                self._subscribers[run_id].discard(queue)
                
                # Clean up empty subscriber sets
                if not self._subscribers[run_id]:
                    del self._subscribers[run_id]
    
    async def prune_old_runs(self, keep_recent: int = 100) -> None:
        """Prune buffers for old runs to prevent unbounded memory growth.
        
        Args:
            keep_recent: Number of recent runs to keep
        """
        async with self._lock:
            if len(self._buffers) <= keep_recent:
                return
            
            # Keep only recent runs (by creation order)
            runs_to_keep = list(self._buffers.keys())[-keep_recent:]
            self._buffers = {
                run_id: buffer
                for run_id, buffer in self._buffers.items()
                if run_id in runs_to_keep
            }
            
            logger.info(f"Pruned old run buffers, keeping {len(runs_to_keep)} recent runs")


# Global event bus instance
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# Router for the /internal/trace endpoint
router = APIRouter()


@router.post("/internal/trace")
async def ingest_trace_event(event: TraceEventModel) -> dict[str, str]:
    """Ingest a trace event from a worker agent.
    
    This is the primary ingestion path for the in-process event bus.
    Workers POST events here; the bus fans out to SSE subscribers.
    
    Best-effort side writes to Postgres/Redis happen in the emitter,
    not here, to keep this endpoint fast and reliable.
    """
    bus = get_event_bus()
    
    # Convert to dict for internal use
    event_dict = event.model_dump(mode="json")
    
    await bus.publish(event_dict)
    
    logger.debug(
        f"[{event.run_id}] Ingested {event.kind} event from {event.agent}: {event.summary}"
    )
    
    return {"status": "ok"}
