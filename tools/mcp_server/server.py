"""FastMCP server exposing LandWatch tools.

Runs on :8010 with streamable-http transport, shared by all four agents.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from landwatch.search import get_detail
from landwatch.tools import TOOL_DESCRIPTION, LandSearchInput, run_search

from agents.common.config import MCP_PORT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the MCP server instance
mcp = FastMCP("LandScout Tools")


@mcp.tool(description=TOOL_DESCRIPTION)
def landwatch_search(
    state: str | None = None,
    region: str | None = None,
    county: str | None = None,
    city: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    acres_min: float | None = None,
    acres_max: float | None = None,
    beds_min: int | None = None,
    baths_min: int | None = None,
    keyword: str | None = None,
    property_types: list[str] | None = None,
    activities: list[str] | None = None,
    geographies: list[str] | None = None,
    land_uses: list[str] | None = None,
    housing_types: list[str] | None = None,
    has_residence: bool | None = None,
    owner_financing: bool = False,
    mineral_rights: bool = False,
    hoa: str | None = None,
    sale_type: str | None = None,
    max_results: int = 25,
) -> str:
    """Search LandWatch for land and rural property listings.
    
    Returns matching listings with price, acreage, location, and broker info
    as a JSON-formatted string. Errors are returned as JSON with an "error" key.
    
    IMPORTANT: This tool reuses the existing LandWatch tool implementation.
    The schema and description are imported from tools/landwatch/landwatch/tools.py
    to ensure consistency and avoid schema drift.
    """
    # Build kwargs dict, filtering out None values for optional params
    kwargs: dict[str, Any] = {}
    if state is not None:
        kwargs["state"] = state
    if region is not None:
        kwargs["region"] = region
    if county is not None:
        kwargs["county"] = county
    if city is not None:
        kwargs["city"] = city
    if price_min is not None:
        kwargs["price_min"] = price_min
    if price_max is not None:
        kwargs["price_max"] = price_max
    if acres_min is not None:
        kwargs["acres_min"] = acres_min
    if acres_max is not None:
        kwargs["acres_max"] = acres_max
    if beds_min is not None:
        kwargs["beds_min"] = beds_min
    if baths_min is not None:
        kwargs["baths_min"] = baths_min
    if keyword is not None:
        kwargs["keyword"] = keyword
    if property_types is not None:
        kwargs["property_types"] = property_types
    if activities is not None:
        kwargs["activities"] = activities
    if geographies is not None:
        kwargs["geographies"] = geographies
    if land_uses is not None:
        kwargs["land_uses"] = land_uses
    if housing_types is not None:
        kwargs["housing_types"] = housing_types
    if has_residence is not None:
        kwargs["has_residence"] = has_residence
    if owner_financing:
        kwargs["owner_financing"] = owner_financing
    if mineral_rights:
        kwargs["mineral_rights"] = mineral_rights
    if hoa is not None:
        kwargs["hoa"] = hoa
    if sale_type is not None:
        kwargs["sale_type"] = sale_type
    kwargs["max_results"] = max_results
    
    # Call the existing tool implementation
    return run_search(**kwargs)


@mcp.tool()
def landwatch_detail(property_id: int) -> str:
    """Fetch full detail for a single LandWatch listing by property ID.
    
    Returns extended information including price history, full description,
    utilities/access details, and amenities as JSON. Used by the Enricher
    to add per-parcel facts beyond the basic search result.
    
    Args:
        property_id: Numeric LandWatch property ID from search results
        
    Returns:
        JSON string with full property detail or error
    """
    try:
        detail = get_detail(property_id)
        return json.dumps(
            {
                "property_id": detail.property_id,
                "title": detail.title,
                "price": detail.price,
                "acres": detail.acres,
                "price_per_acre": detail.price_per_acre,
                "location": {
                    "city": detail.city,
                    "county": detail.county,
                    "state": detail.state_abbreviation,
                    "zip": detail.zip_code,
                },
                "description": detail.description,
                "price_history": [
                    {"date": h.date.isoformat(), "price": h.price}
                    for h in detail.price_history
                ]
                if detail.price_history
                else [],
                "days_on_market": detail.days_on_market,
                "property_types": detail.property_types,
                "beds": detail.beds,
                "baths": detail.baths,
                "broker": {
                    "name": detail.broker.name,
                    "phone": detail.broker.phone,
                }
                if detail.broker
                else None,
                "url": detail.url,
            },
            indent=None,
            default=str,
        )
    except Exception as e:
        logger.error(f"Failed to fetch detail for property {property_id}: {e}")
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def main() -> None:
    """Run the MCP server on port 8010."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    logger.info(f"Starting LandScout MCP server on port {MCP_PORT}")
    
    # Create a wrapper app with CORS and health endpoint
    app = FastAPI(title="LandScout MCP Server")
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add health endpoint
    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "mcp"}
    
    # Temporarily disable FastMCP mount due to library bug
    # TODO: Fix FastMCP integration or switch to direct REST endpoints
    logger.warning("FastMCP mount disabled - MCP tools not available via protocol")
    
    # Run the wrapper app
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=MCP_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
