"""Trace event emission helpers for agents.

Provides a simple API for agents to emit structured trace events that route
to the in-process event bus (primary) with best-effort side writes to
Postgres and Redis when available.

Emitter uses a background daemon worker thread with a queue to ensure emit()
never blocks the caller, even when network or DB operations are slow.
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Literal, Optional

import httpx

from memory.schemas import TraceEvent
from agents.common.config import HTTP_CLIENT_TIMEOUT

logger = logging.getLogger(__name__)

# Maximum size for trace event data fields to prevent bloat
MAX_TRACE_DATA_SIZE = 50_000  # 50KB limit per event data field


def _truncate_large_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Truncate large fields in trace data to prevent event bloat.
    
    Args:
        data: Event data dict or None
        
    Returns:
        Truncated data dict or None if input is None
    """
    if data is None:
        return None
    
    import json
    
    result = {}
    for key, value in data.items():
        # Convert value to string for size check
        if isinstance(value, str):
            value_str = value
        else:
            try:
                value_str = json.dumps(value)
            except (TypeError, ValueError):
                # Fallback to str() if JSON serialization fails
                value_str = str(value)
        
        # Truncate if too large
        if len(value_str) > MAX_TRACE_DATA_SIZE:
            truncated_chars = len(value_str) - MAX_TRACE_DATA_SIZE
            result[key] = value_str[:MAX_TRACE_DATA_SIZE] + f"\n... [truncated {truncated_chars:,} chars]"
            result[f"{key}_truncated"] = True
        else:
            result[key] = value
    
    return result


# Module-level background worker for all emitters
_worker_queue: queue.Queue | None = None
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()


def _trace_worker():
    """Background worker thread that processes trace events.
    
    Maintains a single HTTP client and reuses DB connections for all events,
    avoiding the reconnect overhead that was blocking agents.
    """
    http_client = httpx.Client(timeout=HTTP_CLIENT_TIMEOUT)
    pg_store = None
    redis_store = None
    
    # Initialize DB connections (best-effort)
    try:
        from memory.store import PostgresStore
        pg_store = PostgresStore()
        pg_store.__enter__()
    except Exception as e:
        logger.debug(f"Trace worker: Postgres not available: {e}")
    
    try:
        from memory.store import RedisStore
        redis_store = RedisStore()
        redis_store.__enter__()
    except Exception as e:
        logger.debug(f"Trace worker: Redis not available: {e}")
    
    logger.debug("Trace worker thread started")
    
    while True:
        try:
            # Block until an event arrives (None is the shutdown signal)
            event = _worker_queue.get()
            
            if event is None:
                logger.debug("Trace worker shutting down")
                break
            
            # Primary: HTTP POST to event bus
            try:
                response = http_client.post(
                    f"{event['api_base_url']}/internal/trace",
                    json=event['payload'],
                )
                if not response.is_success:
                    logger.warning(
                        f"Event bus returned {response.status_code} for {event['payload']['kind']} event"
                    )
            except Exception as e:
                logger.error(f"Failed to post trace event to bus: {e}")
            
            # Best-effort: Postgres
            if pg_store:
                try:
                    pg_store.insert_trace_event(
                        run_id=event['payload']['run_id'],
                        agent=event['payload']['agent'],
                        kind=event['payload']['kind'],
                        summary=event['payload']['summary'],
                        data=event['payload'].get('data'),
                    )
                except Exception as e:
                    logger.debug(f"Postgres trace insert failed (non-fatal): {e}")
            
            # Best-effort: Redis
            if redis_store:
                try:
                    redis_store.publish_trace_event(
                        run_id=event['payload']['run_id'],
                        event=event['payload'],
                    )
                except Exception as e:
                    logger.debug(f"Redis trace publish failed (non-fatal): {e}")
            
            _worker_queue.task_done()
            
        except Exception as e:
            logger.error(f"Trace worker error: {e}", exc_info=True)
    
    # Cleanup on shutdown
    http_client.close()
    if pg_store:
        try:
            pg_store.__exit__(None, None, None)
        except Exception:
            pass
    if redis_store:
        try:
            redis_store.__exit__(None, None, None)
        except Exception:
            pass


def _ensure_worker_running():
    """Ensure the background worker thread is running."""
    global _worker_queue, _worker_thread
    
    with _worker_lock:
        if _worker_queue is None:
            _worker_queue = queue.Queue(maxsize=1000)
            _worker_thread = threading.Thread(target=_trace_worker, daemon=True)
            _worker_thread.start()
            
            # Register shutdown handler
            def _shutdown_worker():
                if _worker_queue:
                    _worker_queue.put(None)  # Signal shutdown
                    if _worker_thread and _worker_thread.is_alive():
                        _worker_thread.join(timeout=2.0)
            
            atexit.register(_shutdown_worker)


class TraceEmitter:
    """Emits trace events via a background worker queue.
    
    emit() is non-blocking and never raises. Events are queued to a daemon
    worker thread that handles HTTP POST to the event bus and best-effort
    Postgres/Redis writes with reused connections.
    """
    
    def __init__(
        self,
        run_id: str,
        agent_name: str,
        api_base_url: str = "http://localhost:8000",
    ):
        self.run_id = run_id
        self.agent_name = agent_name
        self.api_base_url = api_base_url
        
        # Ensure worker is running
        _ensure_worker_running()
    
    def emit(
        self,
        kind: Literal[
            "thought",
            "route",
            "a2a_send",
            "a2a_recv",
            "tool_call",
            "tool_result",
            "error",
            "subagent_start",
            "subagent_finish",
            "memory_read",
            "memory_write",
            "context",
            "llm_call",
            "llm_response",
        ],
        summary: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Emit a trace event (non-blocking).
        
        Args:
            kind: Event type (determines UI routing)
            summary: Short human-readable description
            data: Optional structured detail for debug inspection
        """
        # Truncate large data fields to prevent event bloat
        truncated_data = _truncate_large_data(data)
        
        event = TraceEvent(
            run_id=self.run_id,
            ts=datetime.utcnow(),
            agent=self.agent_name,
            kind=kind,
            summary=summary,
            data=truncated_data,
        )
        
        # Queue the event for background processing (never blocks)
        try:
            _worker_queue.put_nowait({
                'api_base_url': self.api_base_url,
                'payload': event.model_dump(mode="json"),
            })
        except queue.Full:
            logger.warning(f"Trace queue full, dropping {kind} event")
        except Exception as e:
            logger.error(f"Failed to queue trace event: {e}")
    
    def close(self) -> None:
        """No-op for API compatibility (worker thread is daemon and shared)."""
        pass
    
    def thought(self, summary: str, data: Optional[dict[str, Any]] = None) -> None:
        """Emit a thought event (routes to Deep-Thoughts panel)."""
        self.emit("thought", summary, data)
    
    def route(self, summary: str, data: Optional[dict[str, Any]] = None) -> None:
        """Emit a routing decision (routes to Logs panel)."""
        self.emit("route", summary, data)
    
    def a2a_send(
        self, target: str, message: dict[str, Any]
    ) -> None:
        """Emit an A2A send event (routes to Logs panel)."""
        self.emit("a2a_send", f"→ {target}", {"target": target, "message": message})
    
    def a2a_recv(
        self, source: str, message: dict[str, Any]
    ) -> None:
        """Emit an A2A receive event (routes to Logs panel)."""
        self.emit("a2a_recv", f"← {source}", {"source": source, "message": message})
    
    def tool_call(
        self, tool_name: str, args: dict[str, Any]
    ) -> None:
        """Emit a tool call event (routes to Logs panel)."""
        self.emit("tool_call", f"🛠 {tool_name}", {"tool": tool_name, "args": args})
    
    def tool_result(
        self, tool_name: str, result: Any, duration_ms: Optional[float] = None
    ) -> None:
        """Emit a tool result event (routes to Logs panel)."""
        data = {"tool": tool_name, "result": result}
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        self.emit("tool_result", f"✓ {tool_name}", data)
    
    def error(self, summary: str, error: str, context: Optional[dict[str, Any]] = None) -> None:
        """Emit an error event (routes to Logs panel)."""
        data = {"error": error}
        if context:
            data["context"] = context
        self.emit("error", summary, data)
    
    def subagent_start(self, subagent: str, task: str) -> None:
        """Emit a subagent start event."""
        self.emit("subagent_start", f"Starting {subagent}", {"subagent": subagent, "task": task})
    
    def subagent_finish(self, subagent: str, duration_ms: float, result_size: int) -> None:
        """Emit a subagent finish event."""
        self.emit(
            "subagent_finish",
            f"Finished {subagent} ({duration_ms:.0f}ms, {result_size} chars)",
            {"subagent": subagent, "duration_ms": duration_ms, "result_size": result_size}
        )
    
    def memory_read(self, operation: str, result: str) -> None:
        """Emit a memory read event."""
        self.emit("memory_read", f"Memory: {operation}", {"operation": operation, "result": result})
    
    def memory_write(self, operation: str, count: int) -> None:
        """Emit a memory write event."""
        self.emit("memory_write", f"Persisted {count} {operation}", {"operation": operation, "count": count})
    
    def context(self, payload: dict[str, Any], estimated_tokens: int) -> None:
        """Emit a context event showing full agent payload."""
        self.emit(
            "context",
            f"Context: ~{estimated_tokens} tokens",
            {
                "payload": payload,  # Include full payload content
                "payload_keys": list(payload.keys()),
                "estimated_tokens": estimated_tokens
            }
        )


def create_trace_emitter(
    run_id: str, agent_name: str, api_base_url: str = "http://localhost:8000"
) -> TraceEmitter:
    """Factory for trace emitters.
    
    Creates a new emitter that posts to the in-process event bus via HTTP.
    
    Args:
        run_id: Run identifier
        agent_name: Name of the agent (supervisor, scout, enricher, scorer)
        api_base_url: Base URL for the API (default: http://localhost:8000)
        
    Returns:
        Configured TraceEmitter
    """
    return TraceEmitter(run_id, agent_name, api_base_url)


def instrument_tool(
    tool_name: str,
    tool_fn: Callable[..., Any],
    emitter: TraceEmitter,
) -> Callable[..., Any]:
    """Instrument a tool function to emit trace events.
    
    Wraps a tool function to automatically emit tool_call and tool_result events.
    
    Args:
        tool_name: Name of the tool
        tool_fn: The tool function to wrap
        emitter: TraceEmitter instance
        
    Returns:
        Wrapped function that emits trace events
    """
    @wraps(tool_fn)
    def wrapper(*args, **kwargs):
        # Emit tool_call
        emitter.tool_call(tool_name, kwargs if kwargs else {"args": args})
        
        # Execute tool
        start_time = time.time()
        try:
            result = tool_fn(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            # Emit tool_result
            emitter.tool_result(tool_name, result, duration_ms)
            
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            emitter.error(f"Tool {tool_name} failed", str(e), {"duration_ms": duration_ms})
            raise
    
    return wrapper
