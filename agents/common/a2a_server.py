"""A2A (Agent-to-Agent) server wrapper for CrewAI agents.

Wraps a single-agent CrewAI Crew in an HTTP-based A2A executor, providing
a uniform protocol for agent-to-agent communication.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from crewai import Agent, Crew, Task
import uvicorn

from .middleware import add_standard_cors, add_health_check

logger = logging.getLogger(__name__)

__all__ = ["TaskRequest", "TaskResponse", "A2ACrewServer"]


class TaskRequest(BaseModel):
    """A2A task request model."""
    
    task_id: str
    run_id: str  # Added for trace event tagging
    task_description: str
    expected_output: str | None = None
    context: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    """A2A task response model."""
    
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None


class A2ACrewServer:
    """A2A server wrapping a single CrewAI agent.
    
    Each agent runs as an independent service on its own port, exposing
    a uniform /message endpoint for synchronous task execution.
    """
    
    def __init__(
        self,
        agent_name: str,
        agent: Agent | None = None,
        port: int = 0,
        trace_callback: Callable[[str, str, dict[str, Any] | None], None] | None = None,
        agent_factory: Callable[[str | None, str | None], Agent] | None = None,
    ):
        """Initialize the A2A server.
        
        Args:
            agent_name: Agent identifier (supervisor, scout, enricher, scorer)
            agent: Configured CrewAI Agent instance (required if agent_factory not provided)
            port: HTTP port to listen on
            trace_callback: Optional callback for trace event emission
                            (called with: event_kind, summary, data)
            agent_factory: Optional factory (provider, model) -> Agent that rebuilds
                          the agent per request with the selected provider/model.
                          If provided, agent parameter is ignored.
        """
        if agent is None and agent_factory is None:
            raise ValueError("Either agent or agent_factory must be provided")
        
        self.agent_name = agent_name
        self.agent = agent
        self.port = port
        self.trace_callback = trace_callback
        self.agent_factory = agent_factory
        
        # Create FastAPI app
        self.app = FastAPI(title=f"{agent_name} A2A Service")
        
        # Add standard middleware and health check
        add_standard_cors(self.app)
        add_health_check(self.app, agent_name)
        
        # Register routes
        @self.app.post("/message", response_model=TaskResponse)
        async def handle_message(request: TaskRequest) -> TaskResponse:
            return await self._handle_task(request)
    
    async def _handle_task(self, request: TaskRequest) -> TaskResponse:
        """Handle incoming A2A task request.
        
        Executes the agent's task and returns the result.
        """
        try:
            # Create trace emitter for this run
            from agents.common.trace import create_trace_emitter
            from agents.common.crewai_events import crewai_trace_handlers
            
            run_id = request.run_id
            emitter = create_trace_emitter(run_id, self.agent_name)
            
            # Extract provider/model from context if present
            context = request.context or {}
            llm_provider = context.get("llm_provider")
            llm_model = context.get("llm_model")
            
            # Build agent with provider/model if factory is provided
            if self.agent_factory is not None:
                agent = self.agent_factory(llm_provider, llm_model)
            else:
                agent = self.agent
            
            # Log the incoming request
            logger.info(
                f"[{run_id}] Received task: {request.task_description[:100]}"
            )
            
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
                f"Starting {self.agent_name}",
                {"subagent": self.agent_name, "task": request.task_description[:200]}
            )
            
            import time
            start_time = time.time()
            
            # Create a CrewAI Task from the A2A request
            task = Task(
                description=request.task_description,
                expected_output=request.expected_output or "Complete task successfully",
                agent=agent,
            )
            
            # Create a single-agent crew and execute with scoped event handlers
            crew = Crew(
                agents=[agent],
                tasks=[task],
                verbose=False,
            )
            
            # Execute crew with CrewAI event handlers for tool call tracing
            with crewai_trace_handlers(run_id, self.agent_name):
                result = await crew.kickoff_async()

            # Prefer structured / raw text over str(CrewOutput), which can
            # include rich panels or prose wrappers that break json.loads.
            result_str: str
            raw = getattr(result, "raw", None)
            json_dict = getattr(result, "json_dict", None)
            if isinstance(raw, str) and raw.strip():
                result_str = raw
            elif json_dict is not None:
                import json

                result_str = json.dumps(json_dict)
            else:
                result_str = str(result)
            
            duration_ms = (time.time() - start_time) * 1000
            
            logger.info(f"[{run_id}] Task completed: {len(result_str)} chars")
            
            # Emit subagent_finish event
            emitter.emit(
                "subagent_finish",
                f"Finished {self.agent_name} ({duration_ms:.0f}ms, {len(result_str)} chars)",
                {"subagent": self.agent_name, "duration_ms": duration_ms, "result_size": len(result_str)}
            )
            
            # Emit route event for completion
            emitter.emit(
                "route",
                f"✓ Task completed: {len(result_str)} chars",
                {"task_id": request.task_id, "result_preview": result_str[:200]},
            )
            
            # Close emitter
            emitter.close()
            
            return TaskResponse(
                task_id=request.task_id,
                status="completed",
                result=result_str,
            )
            
        except Exception as e:
            run_id = request.run_id
            logger.error(f"[{run_id}] Task failed: {e}", exc_info=True)
            
            try:
                from agents.common.trace import create_trace_emitter
                emitter = create_trace_emitter(run_id, self.agent_name)
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
    
    def run(self, host: str = "0.0.0.0") -> None:
        """Start the A2A server.
        
        Blocks until the server is shut down.
        """
        logger.info(f"Starting {self.agent_name} A2A server on port {self.port}")
        uvicorn.run(
            self.app,
            host=host,
            port=self.port,
            log_level="info",
        )
