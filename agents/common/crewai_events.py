"""CrewAI event handlers for trace emission.

Provides a context manager that registers temporary event handlers on the CrewAI
event bus to capture and emit trace events for tool usage and other activities.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


@contextmanager
def crewai_trace_handlers(run_id: str, agent_name: str) -> Generator[None, None, None]:
    """Context manager that registers CrewAI event handlers for trace emission.
    
    Hooks into CrewAI's event bus using scoped handlers to capture tool calls,
    LLM calls, and other events, then emits them as trace events. Handlers are
    automatically cleaned up when the context exits.
    
    Usage:
        with crewai_trace_handlers(run_id, agent_name):
            result = crew.kickoff()
    
    Args:
        run_id: Run identifier for trace correlation
        agent_name: Name of the agent (scout, enricher, scorer)
    """
    try:
        from crewai.events import (
            crewai_event_bus,
            ToolUsageStartedEvent,
            ToolUsageFinishedEvent,
            ToolUsageErrorEvent,
            LLMCallStartedEvent,
            LLMCallCompletedEvent,
        )
        from agents.common.trace import create_trace_emitter
    except ImportError as e:
        logger.warning(f"Could not import CrewAI events: {e}")
        yield  # No-op if imports fail
        return
    
    emitter = create_trace_emitter(run_id, agent_name)
    
    with crewai_event_bus.scoped_handlers():
        # Handler for tool execution start
        @crewai_event_bus.on(ToolUsageStartedEvent)
        def on_tool_started(source: Any, event: ToolUsageStartedEvent) -> None:
            """Emit trace event when a tool execution starts."""
            try:
                tool_name = getattr(event, 'tool_name', 'unknown')
                tool_args = getattr(event, 'arguments', {})
                
                emitter.emit(
                    "tool_call",
                    f"🔧 Calling {tool_name}",
                    {
                        "tool": tool_name,
                        "arguments": tool_args,
                        "agent": agent_name,
                    }
                )
                logger.debug(f"[{agent_name}] Tool started: {tool_name}")
            except Exception as e:
                logger.error(f"Error in tool_started handler: {e}", exc_info=True)
        
        # Handler for tool execution completion
        @crewai_event_bus.on(ToolUsageFinishedEvent)
        def on_tool_finished(source: Any, event: ToolUsageFinishedEvent) -> None:
            """Emit trace event when a tool execution completes."""
            try:
                tool_name = getattr(event, 'tool_name', 'unknown')
                result = getattr(event, 'result', None)
                from_cache = getattr(event, 'from_cache', False)
                
                # Calculate duration if timestamps are available
                duration_ms = None
                if hasattr(event, 'started_at') and hasattr(event, 'finished_at'):
                    duration_ms = (event.finished_at - event.started_at).total_seconds() * 1000
                
                # Truncate result for trace event (keep full result in logs)
                result_summary = str(result)[:500] if result else "No result"
                
                emitter.emit(
                    "tool_result",
                    f"✓ {tool_name} completed" + (" (cached)" if from_cache else ""),
                    {
                        "tool": tool_name,
                        "result_preview": result_summary,
                        "from_cache": from_cache,
                        "duration_ms": duration_ms,
                        "agent": agent_name,
                    }
                )
                logger.debug(
                    f"[{agent_name}] Tool finished: {tool_name}, "
                    f"cached={from_cache}, duration={duration_ms:.0f}ms" if duration_ms else f"{tool_name}"
                )
            except Exception as e:
                logger.error(f"Error in tool_finished handler: {e}", exc_info=True)
        
        # Handler for tool execution errors
        @crewai_event_bus.on(ToolUsageErrorEvent)
        def on_tool_error(source: Any, event: ToolUsageErrorEvent) -> None:
            """Emit trace event when a tool execution fails."""
            try:
                tool_name = getattr(event, 'tool_name', 'unknown')
                error = getattr(event, 'error', 'Unknown error')
                
                emitter.emit(
                    "error",  # Use standard error kind
                    f"❌ {tool_name} failed: {error}",
                    {
                        "tool": tool_name,
                        "error": str(error),
                        "error_type": "tool_execution",
                        "agent": agent_name,
                    }
                )
                logger.error(f"[{agent_name}] Tool error: {tool_name} - {error}")
            except Exception as e:
                logger.error(f"Error in tool_error handler: {e}", exc_info=True)
        
        # Handler for LLM call start
        @crewai_event_bus.on(LLMCallStartedEvent)
        def on_llm_started(source: Any, event: LLMCallStartedEvent) -> None:
            """Emit trace event when an LLM call starts."""
            try:
                messages = getattr(event, 'messages', None)
                tools = getattr(event, 'tools', None)
                temperature = getattr(event, 'temperature', None)
                
                # Calculate message size
                messages_str = str(messages) if messages else ""
                message_size = len(messages_str)
                
                emitter.emit(
                    "llm_call",
                    f"🤖 LLM Call: {message_size:,} chars",
                    {
                        "messages": messages,
                        "tools": tools,
                        "temperature": temperature,
                        "agent": agent_name,
                        "message_size": message_size,
                    }
                )
                logger.debug(f"[{agent_name}] LLM call started: {message_size} chars")
            except Exception as e:
                logger.error(f"Error in llm_started handler: {e}", exc_info=True)
        
        # Handler for LLM call completion
        @crewai_event_bus.on(LLMCallCompletedEvent)
        def on_llm_completed(source: Any, event: LLMCallCompletedEvent) -> None:
            """Emit trace event when an LLM call completes."""
            try:
                response = getattr(event, 'response', None)
                usage = getattr(event, 'usage', None)
                finish_reason = getattr(event, 'finish_reason', None)
                
                # Convert response to string for summary
                response_str = str(response) if response else ""
                response_size = len(response_str)
                
                # Format usage info for summary
                usage_summary = "N/A"
                if usage:
                    if isinstance(usage, dict):
                        prompt_tokens = usage.get('prompt_tokens', 0)
                        completion_tokens = usage.get('completion_tokens', 0)
                        total_tokens = usage.get('total_tokens', 0)
                        usage_summary = f"{total_tokens} tokens (in: {prompt_tokens}, out: {completion_tokens})"
                    else:
                        usage_summary = str(usage)
                
                emitter.emit(
                    "llm_response",
                    f"✓ LLM Response: {usage_summary}",
                    {
                        "response": response_str,
                        "usage": usage,
                        "finish_reason": finish_reason,
                        "agent": agent_name,
                        "response_size": response_size,
                    }
                )
                logger.debug(f"[{agent_name}] LLM call completed: {usage_summary}")
            except Exception as e:
                logger.error(f"Error in llm_completed handler: {e}", exc_info=True)
        
        logger.debug(f"[{agent_name}] Registered scoped CrewAI event handlers for run {run_id}")
        
        # Yield control back to the caller - handlers are active during this block
        yield
        
        # Handlers are automatically cleaned up when exiting the context
        logger.debug(f"[{agent_name}] Cleaned up CrewAI event handlers for run {run_id}")
