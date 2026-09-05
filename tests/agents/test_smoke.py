#!/usr/bin/env python3
"""Smoke test: verify CrewAI can do tool-calling through the gateway.

This script creates a minimal CrewAI agent with a simple search tool and
confirms that tool-calling works end-to-end before any agent implementation
code is written.

Run from repo root: .venv/bin/python agents/common/smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure agents/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from crewai import Agent, Task, Crew
from pydantic import BaseModel, Field

from agents.common import build_llm


class SearchInput(BaseModel):
    """Input schema for the test search tool."""
    
    query: str = Field(description="The search query")
    limit: int = Field(default=5, description="Max results to return")


def mock_search(query: str, limit: int = 5) -> str:
    """Mock search tool that returns canned results."""
    results = [f"Result {i+1} for '{query}'" for i in range(min(limit, 3))]
    return f"Found {len(results)} results: " + ", ".join(results)


def run_smoke_test():
    """Run the smoke test."""
    print("=" * 70)
    print("LandScout LLM Smoke Test")
    print("=" * 70)
    print()
    
    # Build the LLM
    print("1. Building LLM with gateway credentials...")
    try:
        llm = build_llm()
        print(f"   ✓ LLM built successfully")
        print()
    except Exception as e:
        print(f"   ✗ Failed to build LLM: {e}")
        return False
    
    # Create a simple tool
    print("2. Creating test agent with mock search tool...")
    try:
        from crewai.tools import tool
        
        @tool("search")
        def search_tool(query: str, limit: int = 5) -> str:
            """Search for information."""
            return mock_search(query, limit)
        
        agent = Agent(
            role="Test Agent",
            goal="Test tool calling through the gateway",
            backstory="A simple agent for smoke testing",
            tools=[search_tool],
            llm=llm,
            verbose=True,
        )
        print(f"   ✓ Agent created successfully")
        print()
    except Exception as e:
        print(f"   ✗ Failed to create agent: {e}")
        return False
    
    # Create a task that requires tool use
    print("3. Running task that requires tool use...")
    try:
        task = Task(
            description="Search for 'land investment Texas' and tell me what you found.",
            expected_output="A summary of search results",
            agent=agent,
        )
        
        crew = Crew(
            agents=[agent],
            tasks=[task],
            verbose=True,
        )
        
        result = crew.kickoff()
        print()
        print(f"   ✓ Task completed successfully")
        print()
        print("Result:")
        print("-" * 70)
        print(result)
        print("-" * 70)
        print()
        return True
    except Exception as e:
        print(f"   ✗ Task failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print()
    success = run_smoke_test()
    print()
    if success:
        print("✓ Smoke test PASSED - CrewAI can use tools through the gateway")
        sys.exit(0)
    else:
        print("✗ Smoke test FAILED - check errors above")
        sys.exit(1)
