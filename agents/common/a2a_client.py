"""A2A (Agent-to-Agent) client for making blocking calls to other agents."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

_PORT_TO_AGENT = {
    8002: "scout",
    8003: "enricher",
    8004: "scorer",
    8001: "supervisor",
}


def _agent_label_from_url(url: str) -> str:
    """Map an A2A URL to a short agent name for traces / UI."""
    try:
        # http://localhost:8002/message → 8002
        host_port = url.split("//", 1)[-1].split("/", 1)[0]
        port = int(host_port.rsplit(":", 1)[-1])
        return _PORT_TO_AGENT.get(port, host_port)
    except (ValueError, IndexError):
        return url


class TaskRequest:
    """A2A task request."""
    
    def __init__(
        self,
        task_id: str,
        run_id: str,  # Added for trace event tagging
        task_description: str,
        expected_output: str | None = None,
        context: dict[str, Any] | None = None,
    ):
        self.task_id = task_id
        self.run_id = run_id
        self.task_description = task_description
        self.expected_output = expected_output
        self.context = context
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "task_description": self.task_description,
            "expected_output": self.expected_output,
            "context": self.context,
        }


class A2ACrewClient:
    """Client for making synchronous A2A calls to other agents.
    
    Used by the Supervisor to delegate tasks to Scout, Enricher, and Scorer.
    """
    
    def __init__(
        self,
        agent_name: str,
        trace_callback: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ):
        """Initialize the A2A client.
        
        Args:
            agent_name: Name of the calling agent (for logging/tracing)
            trace_callback: Optional callback for trace event emission
                            (called with: event_kind, summary, data)
        """
        self.agent_name = agent_name
        self.trace_callback = trace_callback
    
    def send_task(
        self,
        target_url: str,
        run_id: str,  # Added for trace event tagging
        task_description: str,
        expected_output: str | None = None,
        context: dict[str, Any] | None = None,
        timeout: int = 300,
    ) -> str:
        """Send a task to another agent and wait for the result.
        
        Args:
            target_url: Full URL of the target agent's A2A endpoint
                       (e.g., "http://localhost:8002/message")
            run_id: Run identifier for trace event tagging
            task_description: Natural language task description
            expected_output: Optional description of expected result format
            context: Optional structured context data
            timeout: Request timeout in seconds
            
        Returns:
            Task result as a string
            
        Raises:
            RuntimeError: If the task fails or times out
        """
        task_id = str(uuid.uuid4())
        
        logger.info(
            f"[{run_id}] Sending task to {target_url}: "
            f"{task_description[:100]}"
        )
        
        target_label = _agent_label_from_url(target_url)
        if self.trace_callback:
            self.trace_callback(
                "a2a_send",
                f"→ {target_label}: {task_description[:60]}",
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "target": target_url,
                    "target_agent": target_label,
                    "full_description": task_description,
                    "context": context,
                },
            )
        
        # Create the request payload
        payload = {
            "task_id": task_id,
            "run_id": run_id,
            "task_description": task_description,
            "expected_output": expected_output,
            "context": context,
        }
        
        # Send HTTP POST request
        import time
        start_time = time.time()
        
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(target_url, json=payload)
                if response.is_error:
                    body_preview = response.text[:500]
                    logger.error(
                        f"[{run_id}] HTTP {response.status_code} from "
                        f"{target_url}: {body_preview}"
                    )
                response.raise_for_status()
        
        except httpx.TimeoutException as e:
            error_msg = f"Agent {target_label} timed out after {timeout}s"
            logger.error(f"[{run_id}] {error_msg}")
            
            if self.trace_callback:
                self.trace_callback(
                    "error",
                    f"✗ {target_label} timed out after {timeout}s",
                    {
                        "task_id": task_id,
                        "target": target_url,
                        "timeout_seconds": timeout,
                        "error": str(e),
                    },
                )
            
            raise TimeoutError(error_msg) from e
        
        except httpx.HTTPError as e:
            logger.error(
                f"[{run_id}] HTTP error calling {target_url}: {e}",
                exc_info=True,
            )
            
            if self.trace_callback:
                self.trace_callback(
                    "error",
                    f"✗ A2A HTTP error: {type(e).__name__}",
                    {
                        "task_id": task_id,
                        "target": target_url,
                        "error": str(e),
                    },
                )
            
            raise RuntimeError(
                f"Failed to call {target_url}: {type(e).__name__}: {e}"
            ) from e
        
        except Exception as e:
            logger.error(
                f"[{run_id}] A2A call to {target_url} failed: {e}",
                exc_info=True,
            )
            
            if self.trace_callback:
                self.trace_callback(
                    "error",
                    f"✗ A2A call exception: {type(e).__name__}",
                    {
                        "task_id": task_id,
                        "target": target_url,
                        "error": str(e),
                    },
                )
            
            raise RuntimeError(
                f"Failed to call {target_url}: {type(e).__name__}: {e}"
            ) from e
        
        # Parse response after all exception handling
        try:
                
                data = response.json()
                
                if data.get("status") != "completed":
                    error_msg = data.get("error", "Task did not complete successfully")
                    logger.error(
                        f"[{run_id}] Task {task_id} failed: {error_msg}"
                    )
                    
                    if self.trace_callback:
                        self.trace_callback(
                            "error",
                            f"✗ A2A call failed: {data.get('status')}",
                            {
                                "task_id": task_id,
                                "target": target_url,
                                "status": data.get("status"),
                                "error": error_msg,
                            },
                        )
                    
                    raise RuntimeError(
                        f"Task {task_id} to {target_url} failed: {error_msg}"
                    )
                
                result = data.get("result", "")
                
                # Capture timing
                duration_ms = (time.time() - start_time) * 1000
                http_duration_ms = response.elapsed.total_seconds() * 1000
                
                logger.info(
                    f"[{run_id}] Task {task_id} completed: {len(result)} chars in {duration_ms:.0f}ms"
                )
                
                if self.trace_callback:
                    self.trace_callback(
                        "a2a_recv",
                        f"← {target_label}: {len(result)} chars in {duration_ms:.0f}ms",
                        {
                            "task_id": task_id,
                            "target": target_url,
                            "target_agent": target_label,
                            "result_preview": result[:200],
                            "duration_ms": duration_ms,
                            "http_duration_ms": http_duration_ms,
                        },
                    )
                
                return result
                
        except httpx.HTTPError as e:
            logger.error(
                f"[{run_id}] HTTP error calling {target_url}: {e}",
                exc_info=True,
            )
            
            if self.trace_callback:
                self.trace_callback(
                    "error",
                    f"✗ A2A HTTP error: {type(e).__name__}",
                    {
                        "task_id": task_id,
                        "target": target_url,
                        "error": str(e),
                    },
                )
            
            raise RuntimeError(
                f"Failed to call {target_url}: {type(e).__name__}: {e}"
            ) from e
        except Exception as e:
            logger.error(
                f"[{run_id}] A2A call to {target_url} failed: {e}",
                exc_info=True,
            )
            
            if self.trace_callback:
                self.trace_callback(
                    "error",
                    f"✗ A2A call exception: {type(e).__name__}",
                    {
                        "task_id": task_id,
                        "target": target_url,
                        "error": str(e),
                    },
                )
            
            raise RuntimeError(
                f"Failed to call {target_url}: {type(e).__name__}: {e}"
            ) from e


def make_agent_url(port: int, path: str = "/message") -> str:
    """Construct an agent URL from port and path.
    
    Args:
        port: Agent's port number
        path: API path (default: /message for A2A)
        
    Returns:
        Full URL string
    """
    return f"http://localhost:{port}{path}"
