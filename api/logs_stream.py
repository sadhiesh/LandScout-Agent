"""Log streaming endpoints for real-time service log viewing.

Provides SSE streaming of all service logs (api, supervisor, scout, enricher,
scorer, mcp) and backfill endpoints for initial state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Service log files relative to repo root
LOG_FILES = {
    "api": "logs/api.log",
    "supervisor": "logs/supervisor.log",
    "scout": "logs/scout.log",
    "enricher": "logs/enricher.log",
    "scorer": "logs/scorer.log",
    "mcp": "logs/mcp.log",
}


def _get_log_path(service: str) -> Path:
    """Get absolute path to a log file."""
    repo_root = Path(__file__).parent.parent
    return repo_root / LOG_FILES[service]


async def _tail_log_file(service: str, file_path: Path) -> AsyncGenerator[dict, None]:
    """Tail a log file and yield new lines as they appear.
    
    Uses seek-to-end plus poll loop to avoid blocking the event loop.
    """
    if not file_path.exists():
        logger.warning(f"Log file not found: {file_path}")
        return
    
    # Open file and seek to end
    def _read_new_lines():
        try:
            with open(file_path, 'r') as f:
                # Seek to end
                f.seek(0, 2)
                
                while True:
                    line = f.readline()
                    if not line:
                        return None  # No new data
                    yield line.rstrip('\n')
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return None
    
    # Initial seek to end
    with open(file_path, 'r') as f:
        f.seek(0, 2)
        position = f.tell()
    
    while True:
        try:
            # Read new lines in a thread to avoid blocking
            with open(file_path, 'r') as f:
                f.seek(position)
                lines = []
                for line in f:
                    lines.append(line.rstrip('\n'))
                position = f.tell()
            
            # Yield each new line
            for line in lines:
                if line:  # Skip empty lines
                    yield {
                        "service": service,
                        "line": line,
                    }
            
            # Poll interval
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error tailing {service} log: {e}")
            await asyncio.sleep(1.0)


@router.get("/logs/stream")
async def stream_logs():
    """SSE stream of all service logs.
    
    Tails every log file and emits lines as they arrive with service labels.
    """
    async def event_generator():
        """Generate SSE events from all log files."""
        # Create tail coroutines for each service
        tasks = []
        for service, log_file in LOG_FILES.items():
            file_path = _get_log_path(service)
            tasks.append(_tail_log_file(service, file_path))
        
        # Merge all streams
        try:
            async for log_event in _merge_async_iterators(tasks):
                yield f"data: {json.dumps(log_event)}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("Log stream client disconnected")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _merge_async_iterators(iterators):
    """Merge multiple async iterators into one, yielding items as they arrive."""
    tasks = {asyncio.create_task(_next_from_iter(it)): it for it in iterators}
    
    while tasks:
        done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        
        for task in done:
            iterator = tasks.pop(task)
            try:
                result = task.result()
                if result is not None:
                    yield result
                    # Schedule next read from this iterator
                    new_task = asyncio.create_task(_next_from_iter(iterator))
                    tasks[new_task] = iterator
            except StopAsyncIteration:
                pass  # Iterator exhausted
            except Exception as e:
                logger.error(f"Error in merged iterator: {e}")


async def _next_from_iter(iterator):
    """Get next item from async iterator or raise StopAsyncIteration."""
    return await iterator.__anext__()


@router.get("/logs/tail")
async def tail_logs(
    service: str = Query(None, description="Service to tail (omit for all)"),
    lines: int = Query(200, description="Number of lines to return"),
):
    """Get recent lines from log files for backfill.
    
    Returns the last N lines from specified service or all services.
    """
    def _read_tail(file_path: Path, n: int) -> list[str]:
        """Read last N lines from a file."""
        if not file_path.exists():
            return []
        
        try:
            with open(file_path, 'r') as f:
                # Read all lines (for small log files this is fine)
                all_lines = f.readlines()
                return [line.rstrip('\n') for line in all_lines[-n:]]
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return []
    
    result = {}
    
    if service:
        # Single service
        if service not in LOG_FILES:
            return {"error": f"Unknown service: {service}"}
        
        file_path = _get_log_path(service)
        result[service] = await asyncio.to_thread(_read_tail, file_path, lines)
    else:
        # All services
        for svc, log_file in LOG_FILES.items():
            file_path = _get_log_path(svc)
            result[svc] = await asyncio.to_thread(_read_tail, file_path, lines)
    
    return result
