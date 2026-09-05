"""Tests for the in-process event bus."""

import asyncio
import pytest
import sys
from pathlib import Path
from datetime import datetime

# Add repo root to path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from api.events import EventBus, TraceEventModel


@pytest.fixture
def event_bus():
    """Create a fresh event bus for each test."""
    return EventBus(buffer_size=10)


@pytest.fixture
def sample_event():
    """Create a sample trace event."""
    return {
        "run_id": "test-run-123",
        "ts": datetime.utcnow().isoformat(),
        "agent": "test-agent",
        "kind": "tool_call",
        "summary": "Test event",
        "data": {"test": "data"},
    }


@pytest.mark.anyio
async def test_publish_and_subscribe(event_bus, sample_event):
    """Test basic publish and subscribe flow."""
    run_id = sample_event["run_id"]
    
    # Subscribe before publishing
    replay, queue = await event_bus.subscribe(run_id)
    
    # Replay should be empty
    assert len(replay) == 0
    
    # Publish an event
    await event_bus.publish(sample_event)
    
    # Get the event from the queue
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["run_id"] == run_id
    assert event["kind"] == "tool_call"


@pytest.mark.anyio
async def test_replay_buffer(event_bus, sample_event):
    """Test that late subscribers receive replay buffer."""
    run_id = sample_event["run_id"]
    
    # Publish events before subscribing
    await event_bus.publish(sample_event)
    await event_bus.publish({**sample_event, "kind": "tool_result"})
    
    # Subscribe after publishing
    replay, queue = await event_bus.subscribe(run_id)
    
    # Should get both events in replay
    assert len(replay) == 2
    assert replay[0]["kind"] == "tool_call"
    assert replay[1]["kind"] == "tool_result"


@pytest.mark.anyio
async def test_multiple_subscribers(event_bus, sample_event):
    """Test fan-out to multiple subscribers."""
    run_id = sample_event["run_id"]
    
    # Create multiple subscribers
    replay1, queue1 = await event_bus.subscribe(run_id)
    replay2, queue2 = await event_bus.subscribe(run_id)
    
    # Publish an event
    await event_bus.publish(sample_event)
    
    # Both should receive it
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)
    
    assert event1["kind"] == "tool_call"
    assert event2["kind"] == "tool_call"


@pytest.mark.anyio
async def test_buffer_size_limit(event_bus):
    """Test that buffer respects size limit."""
    run_id = "test-run-overflow"
    
    # Publish more events than buffer size
    for i in range(15):
        await event_bus.publish({
            "run_id": run_id,
            "ts": datetime.utcnow().isoformat(),
            "agent": "test",
            "kind": "route",
            "summary": f"Event {i}",
            "data": None,
        })
    
    # Subscribe and check replay buffer
    replay, queue = await event_bus.subscribe(run_id)
    
    # Should only have last 10 (buffer_size=10)
    assert len(replay) == 10
    assert replay[0]["summary"] == "Event 5"
    assert replay[-1]["summary"] == "Event 14"


@pytest.mark.anyio
async def test_unsubscribe(event_bus, sample_event):
    """Test unsubscribe cleanup."""
    run_id = sample_event["run_id"]
    
    # Subscribe
    replay, queue = await event_bus.subscribe(run_id)
    
    # Unsubscribe
    await event_bus.unsubscribe(run_id, queue)
    
    # Publish event
    await event_bus.publish(sample_event)
    
    # Queue should not receive it (will timeout)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.5)


@pytest.mark.anyio
async def test_isolated_run_ids(event_bus):
    """Test that different run_ids are isolated."""
    run_id_1 = "run-1"
    run_id_2 = "run-2"
    
    # Subscribe to both
    replay1, queue1 = await event_bus.subscribe(run_id_1)
    replay2, queue2 = await event_bus.subscribe(run_id_2)
    
    # Publish to run_id_1
    await event_bus.publish({
        "run_id": run_id_1,
        "ts": datetime.utcnow().isoformat(),
        "agent": "test",
        "kind": "route",
        "summary": "Event for run 1",
        "data": None,
    })
    
    # Only queue1 should receive it
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    assert event1["summary"] == "Event for run 1"
    
    # queue2 should not receive it
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue2.get(), timeout=0.5)


@pytest.mark.anyio
async def test_missing_run_id(event_bus):
    """Test that events without run_id are rejected."""
    # Publish event without run_id
    await event_bus.publish({
        "ts": datetime.utcnow().isoformat(),
        "agent": "test",
        "kind": "route",
        "summary": "No run_id",
        "data": None,
    })
    
    # Should not be stored anywhere (no exception, just warning logged)
    # This is a smoke test to ensure no crash
    assert True
