"""Agent tool wrappers for LandWatch search.

Exposes the search as a LangChain ``StructuredTool`` and, when ``crewai`` is
installed, as a CrewAI ``BaseTool``::

    from landwatch.tools import build_langchain_tool

    tool = build_langchain_tool()
    agent = create_agent(model, tools=[tool])

The tool takes plain strings and lists rather than the ``PropertyType`` bitmask
used internally, because language models handle named values far more reliably
than integer flags.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .filters import FILTER_CATALOG, coerce_value
from .models import SearchCriteria
from .search import collect
from .url import build_url
from .vocab import (
    Activity,
    Geography,
    Hoa,
    HousingType,
    LandUse,
    MarketStatus,
    PropertyType,
    SaleType,
)

TOOL_NAME = "landwatch_search"


def _options(filter_name: str) -> str:
    """The accepted values of one filter, as a comma-separated list.

    Read from the catalog rather than restated so the tool description cannot
    drift from the actual vocabulary.
    """
    return ", ".join(FILTER_CATALOG[filter_name].value_names)


_PROPERTY_TYPE_NAMES = _options("property_types")

TOOL_DESCRIPTION = (
    "Search LandWatch for land and rural property for sale in the United States. "
    "Use this to find listings matching a buyer's criteria such as location, price, "
    "acreage and property type. Returns matching listings with price, acreage, "
    "price per acre, location, broker and listing URL.\n\n"
    f"Valid property_types: {_PROPERTY_TYPE_NAMES}.\n"
    f"Valid activities: {_options('activities')}.\n"
    f"Valid geographies (terrain, not location): {_options('geographies')}.\n"
    f"Valid land_uses: {_options('land_uses')}.\n"
    f"Valid housing_types: {_options('housing_types')}.\n"
    f"Valid hoa: {_options('hoa')}.\n"
    f"Valid sale_type: {_options('sale_type')}.\n"
    "Set only one of region, county or city, and always pass state alongside them. "
    "Use keyword for wording that no other filter captures, e.g. 'creek frontage'.\n"
    "For any filter you do not want to apply, pass null for a text or number filter, "
    "an empty list for a list filter, and false for a flag."
)


class LandSearchInput(BaseModel):
    """Land search criteria, in the plain form an LLM can produce reliably."""

    state: str | None = Field(
        default=None, description="State name or two-letter abbreviation, e.g. 'texas' or 'TX'."
    )
    region: str | None = Field(default=None, description="Region name, e.g. 'texoma'.")
    county: str | None = Field(default=None, description="County name without the word 'county'.")
    city: str | None = Field(default=None, description="City name.")

    price_min: int | None = Field(default=None, description="Minimum price in US dollars.")
    price_max: int | None = Field(default=None, description="Maximum price in US dollars.")
    acres_min: float | None = Field(default=None, description="Minimum acreage.")
    acres_max: float | None = Field(default=None, description="Maximum acreage.")
    beds_min: int | None = Field(default=None, description="Minimum bedrooms.")
    baths_min: int | None = Field(default=None, description="Minimum bathrooms.")

    keyword: str | None = Field(
        default=None,
        description=(
            "Free-text search over listing titles and descriptions, for wording no "
            "other filter covers, e.g. 'creek frontage' or 'barn'."
        ),
    )

    property_types: list[str] = Field(
        default_factory=list,
        description=f"Property types to include. Options: {_PROPERTY_TYPE_NAMES}.",
    )
    activities: list[str] = Field(
        default_factory=list,
        description=f"Recreational activities. Options: {_options('activities')}.",
    )
    geographies: list[str] = Field(
        default_factory=list,
        description=(
            "Terrain and setting of the land, not its location. "
            f"Options: {_options('geographies')}."
        ),
    )
    land_uses: list[str] = Field(
        default_factory=list,
        description=f"Current land use. Options: {_options('land_uses')}.",
    )
    housing_types: list[str] = Field(
        default_factory=list,
        description=f"Structure types. Options: {_options('housing_types')}.",
    )

    has_residence: bool | None = Field(
        default=None, description="True to require a house on the property, False to exclude one."
    )
    owner_financing: bool | None = Field(default=False, description="Only owner-financed listings.")
    mineral_rights: bool | None = Field(default=False, description="Only listings including mineral rights.")
    hoa: str | None = Field(
        default=None, description=f"HOA requirement. Options: {_options('hoa')}."
    )
    sale_type: str | None = Field(
        default=None,
        description=f"Restrict to conventional listings or auctions. Options: {_options('sale_type')}.",
    )

    max_results: int = Field(
        default=25,
        description=(
            "Maximum listings to return (1-200 inclusive; 25 per page fetched). "
            "Values outside 1-200 are rejected."
        ),
    )

    @field_validator("max_results")
    @classmethod
    def _validate_max_results(cls, value: int) -> int:
        # Bounds are enforced here, not via Field(ge/le), because Bedrock Claude
        # rejects JSON Schema minimum/maximum on integer tool parameters.
        if value < 1 or value > 200:
            raise ValueError("max_results must be between 1 and 200")
        return value


def _coerce_types(names: list[str]) -> PropertyType | None:
    combined: PropertyType | None = None
    for name in names:
        key = name.strip().upper().replace("-", "_").replace(" ", "_")
        if key not in PropertyType.__members__:
            raise ValueError(
                f"unknown property type '{name}'. Valid options: {_PROPERTY_TYPE_NAMES}"
            )
        flag = PropertyType[key]
        combined = flag if combined is None else combined | flag
    return combined


def _coerce_enums(values: list[str], enum_cls: Any) -> list[Any]:
    return [coerce_value(enum_cls, value) for value in values]


def to_criteria(payload: LandSearchInput) -> SearchCriteria:
    """Translate agent-friendly input into the internal SearchCriteria."""
    return SearchCriteria(
        state=payload.state,
        region=payload.region,
        county=payload.county,
        city=payload.city,
        keyword=payload.keyword,
        price_min=payload.price_min,
        price_max=payload.price_max,
        acres_min=payload.acres_min,
        acres_max=payload.acres_max,
        beds_min=payload.beds_min,
        baths_min=payload.baths_min,
        property_types=_coerce_types(payload.property_types),
        activities=_coerce_enums(payload.activities, Activity),
        geographies=_coerce_enums(payload.geographies, Geography),
        land_uses=_coerce_enums(payload.land_uses, LandUse),
        housing_types=_coerce_enums(payload.housing_types, HousingType),
        hoa=coerce_value(Hoa, payload.hoa) if payload.hoa else None,
        sale_type=coerce_value(SaleType, payload.sale_type) if payload.sale_type else None,
        has_residence=payload.has_residence,
        owner_financing=payload.owner_financing or False,
        mineral_rights=payload.mineral_rights or False,
        market_statuses=[MarketStatus.AVAILABLE],
    )


def run_search(**kwargs: Any) -> str:
    """Execute a LandWatch search and return a compact JSON summary.

    Errors are returned as JSON rather than raised, so an agent can read the
    message and retry with corrected arguments.
    """
    try:
        payload = LandSearchInput(**kwargs)
        criteria = to_criteria(payload)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    pages = max(1, -(-payload.max_results // 25))
    try:
        result = collect(criteria, max_pages=pages, max_listings=payload.max_results)
    except Exception as exc:  # noqa: BLE001 - surface failures to the agent as text
        return json.dumps({"error": f"{type(exc).__name__}: {exc}", "url": build_url(criteria)})

    return json.dumps(
        {
            "search_url": result.url,
            "total_matching": result.total_count,
            "returned": len(result.listings),
            "location": result.location_name,
            "facets": [
                {
                    "section": section.section,
                    "options": [
                        {
                            "label": option.label,
                            "count": option.count,
                            "id": option.facet_id,
                            "relative_url_path": option.relative_url_path,
                        }
                        for option in section.options
                    ],
                }
                for section in result.facets
            ],
            "listings": [
                {
                    "property_id": listing.property_id,
                    "listing_id": listing.listing_id,
                    "title": listing.title,
                    "price": listing.price,
                    "acres": listing.acres,
                    "price_per_acre": listing.price_per_acre,
                    "latitude": listing.latitude,
                    "longitude": listing.longitude,
                    "address": listing.address,
                    "city": listing.city,
                    "county": listing.county,
                    "state": listing.state_abbreviation,
                    "zip_code": listing.zip_code,
                    "property_types": listing.property_types,
                    "beds": listing.beds,
                    "baths": listing.baths,
                    "broker": listing.broker.name if listing.broker else None,
                    "url": listing.url,
                }
                for listing in result.listings
            ],
        },
        indent=None,
        default=str,
    )


def build_langchain_tool() -> Any:
    """Build a LangChain ``StructuredTool`` for LandWatch search."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ImportError(
            "LangChain is required for this tool. Install it with: pip install langchain-core"
        ) from exc

    return StructuredTool.from_function(
        func=run_search,
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        args_schema=LandSearchInput,
    )


def build_crewai_tool() -> Any:
    """Build a CrewAI ``BaseTool`` for LandWatch search.

    CrewAI is an optional dependency; install it with ``pip install crewai``.
    """
    try:
        from crewai.tools import BaseTool
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "CrewAI is not installed. Install it with: pip install crewai"
        ) from exc

    class LandWatchSearchTool(BaseTool):  # type: ignore[misc, valid-type]
        name: str = TOOL_NAME
        description: str = TOOL_DESCRIPTION
        args_schema: type[BaseModel] = LandSearchInput
        # Return the tool's JSON directly so Scout does not spend a second LLM
        # turn reserializing large listing payloads.
        result_as_answer: bool = True

        def _run(self, **kwargs: Any) -> str:
            return run_search(**kwargs)

    return LandWatchSearchTool()
