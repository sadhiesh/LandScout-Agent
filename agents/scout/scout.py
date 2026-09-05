"""Scout Agent — land parcel search.

Port 8002. Turns investment criteria into structured searches and returns
raw parcel candidates.
"""

from __future__ import annotations

import logging

from crewai import Agent
from landwatch.tools import build_crewai_tool

from agents.common import (
    A2ACrewServer,
    SCOUT_PORT,
    build_llm,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_scout_agent(provider: str | None = None, model: str | None = None) -> Agent:
    """Create the Scout agent with landwatch_search tool access.

    Uses the catalog-backed CrewAI tool from ``landwatch.tools`` — do not
    redeclare the search schema here (see tools/landwatch/CLAUDE.md).
    
    Args:
        provider: Optional LLM provider override
        model: Optional LLM model override
    """
    llm = build_llm(provider=provider, model=model)
    landwatch_tool = build_crewai_tool()

    agent = Agent(
        role="Land Parcel Scout",
        goal=(
            "Find land and rural property listings that match the buyer's investment "
            "criteria using LandWatch search"
        ),
        backstory=(
            "You are an expert land scout specialized in finding rural property "
            "listings in the United States. You translate buyer investment criteria "
            "into precise LandWatch searches, understanding the nuances of property "
            "types, locations, acreage ranges, and pricing. You always return the "
            "search URL so the query can be reproduced. You prefer one well-formed "
            "search over multiple speculative ones."
        ),
        tools=[landwatch_tool],
        llm=llm,
        verbose=True,
    )

    return agent


def main() -> None:
    """Run the Scout agent as an A2A server."""
    logger.info("Starting Scout agent...")

    # Use agent_factory instead of a fixed agent to support per-request model selection
    server = A2ACrewServer(
        agent_name="scout",
        agent_factory=create_scout_agent,
        port=SCOUT_PORT,
        trace_callback=None,  # Will be created per-request with run_id
    )

    server.run()


if __name__ == "__main__":
    main()
