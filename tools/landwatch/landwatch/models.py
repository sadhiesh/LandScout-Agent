"""Structured input and output models for LandWatch searches."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .vocab import (
    Activity,
    Geography,
    Hoa,
    HousingType,
    LandUse,
    MarketStatus,
    PropertyType,
    SaleType,
    slugify,
)


class SearchCriteria(BaseModel):
    """Land-buying criteria, which ``url.build_path`` turns into a search URL.

    Only one geography may be set. Omitting ``state`` searches nationwide.
    """

    model_config = ConfigDict(use_enum_values=False, extra="forbid")

    state: str | None = Field(
        default=None,
        description="State name or two-letter abbreviation, e.g. 'texas' or 'TX'.",
    )
    region: str | None = Field(
        default=None, description="Region name, e.g. 'texoma'. Mutually exclusive with county/city."
    )
    county: str | None = Field(
        default=None, description="County name, e.g. 'grayson'. Requires state."
    )
    city: str | None = Field(default=None, description="City name, e.g. 'howe'. Requires state.")

    property_types: PropertyType | None = Field(
        default=None, description="Property types to include; combined with bitwise OR."
    )

    price_min: int | None = Field(default=None, ge=0, description="Minimum price in USD.")
    price_max: int | None = Field(default=None, ge=0, description="Maximum price in USD.")
    acres_min: float | None = Field(default=None, ge=0, description="Minimum parcel size in acres.")
    acres_max: float | None = Field(default=None, ge=0, description="Maximum parcel size in acres.")
    sqft_min: int | None = Field(default=None, ge=0, description="Minimum home square footage.")
    sqft_max: int | None = Field(default=None, ge=0, description="Maximum home square footage.")
    beds_min: int | None = Field(default=None, ge=1, description="Minimum bedrooms.")
    baths_min: int | None = Field(default=None, ge=1, description="Minimum bathrooms.")

    keyword: str | None = Field(
        default=None,
        description="Free-text search over listing titles and descriptions, e.g. 'undeveloped'.",
    )

    activities: list[Activity] = Field(default_factory=list, description="Recreational activities.")
    geographies: list[Geography] = Field(
        default_factory=list,
        description="Terrain and setting, e.g. mountain or off-grid. Not a place filter.",
    )
    land_uses: list[LandUse] = Field(default_factory=list, description="Current land use.")
    housing_types: list[HousingType] = Field(default_factory=list, description="Structure types.")
    hoa: Hoa | None = Field(default=None, description="HOA requirement.")
    sale_type: SaleType | None = Field(
        default=None, description="Restrict to conventional listings or auctions."
    )
    market_statuses: list[MarketStatus] = Field(
        default_factory=list, description="Listing availability; defaults to all statuses."
    )

    has_residence: bool | None = Field(
        default=None, description="True requires a house on the land, False excludes one."
    )
    owner_financing: bool = False
    mineral_rights: bool = False
    virtual_tour: bool = False
    exterior_tour: bool = False
    has_video: bool = False
    custom_map: bool = False

    price_reduction_days: int | None = Field(
        default=None,
        description="Only listings reduced in the last N days, e.g. 30, 60 or 90.",
    )

    sort_order_id: int | None = Field(
        default=None,
        description=(
            "LandWatch's raw sort order id. Passed through as-is; the label mapping "
            "is undocumented."
        ),
    )

    page: int = Field(default=1, ge=1, description="1-based result page.")

    @model_validator(mode="after")
    def _check(self) -> SearchCriteria:
        geographies = [("region", self.region), ("county", self.county), ("city", self.city)]
        supplied = [name for name, value in geographies if value]
        if len(supplied) > 1:
            raise ValueError(
                f"only one of region/county/city may be set, got: {', '.join(supplied)}"
            )
        if supplied and not self.state:
            raise ValueError(f"{supplied[0]} requires 'state' to be set")
        if self.price_min and self.price_max and self.price_min > self.price_max:
            raise ValueError("price_min must not exceed price_max")
        if self.acres_min and self.acres_max and self.acres_min > self.acres_max:
            raise ValueError("acres_min must not exceed acres_max")
        if self.sqft_min and self.sqft_max and self.sqft_min > self.sqft_max:
            raise ValueError("sqft_min must not exceed sqft_max")
        if self.keyword is not None and not slugify(self.keyword):
            # A keyword of only punctuation would slugify away and silently
            # produce the bare segment "keyword-".
            raise ValueError(f"keyword {self.keyword!r} contains no searchable characters")
        return self


class Broker(BaseModel):
    """Listing agent or company."""

    name: str | None = None
    company: str | None = None
    phone: str | None = None
    profile_url: str | None = None


class PriceEvent(BaseModel):
    """One entry in a listing's price/acreage history."""

    event: str
    date: dt.date | None = None
    price: float | None = None
    price_change_percent: float | None = None
    acres: float | None = None


class Listing(BaseModel):
    """A single land listing from a search result page."""

    property_id: int = Field(description="LandWatch public property id, used for detail lookups.")
    listing_id: int | None = None
    title: str | None = None
    url: str | None = Field(default=None, description="Absolute listing URL.")

    price: int | None = None
    price_display: str | None = None
    price_per_acre: float | None = None
    price_change_amount: int | None = None
    price_change_percent: float | None = None

    acres: float | None = None
    acres_display: str | None = None

    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    state_abbreviation: str | None = None
    zip_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    property_types: list[str] = Field(default_factory=list)
    beds: float | None = None
    baths: float | None = None
    home_sqft: int | None = None
    has_house: bool | None = None

    description: str | None = None
    image_count: int = 0
    image_urls: list[str] = Field(default_factory=list)

    broker: Broker | None = None

    listed_date: dt.datetime | None = None
    last_updated: dt.datetime | None = None


class FacetOption(BaseModel):
    """One narrowing option LandWatch advertises for the current search."""

    label: str
    count: int = 0
    relative_url_path: str | None = None
    facet_id: int | None = None


class FacetSection(BaseModel):
    """One facet section from the search payload, e.g. City or Price."""

    section: str
    options: list[FacetOption] = Field(default_factory=list)


class SearchResult(BaseModel):
    """A page of search results plus the context needed to page through them."""

    criteria: SearchCriteria
    url: str = Field(description="The search URL that produced these results.")
    path: str = Field(description="The URL path built from the criteria.")

    total_count: int = Field(description="Total matching listings across all pages.")
    page: int
    page_size: int
    total_pages: int

    listings: list[Listing] = Field(default_factory=list)
    facets: list[FacetSection] = Field(default_factory=list)

    location_name: str | None = None
    next_page_path: str | None = None
    applied_filters: list[str] = Field(default_factory=list)

    @property
    def has_next_page(self) -> bool:
        return self.next_page_path is not None


class PropertyDetail(BaseModel):
    """Full detail for one listing, including price history."""

    property_id: int
    listing_id: int | None = None
    title: str | None = None
    url: str | None = None

    price: float | None = None
    acres: float | None = None
    home_sqft: int | None = None
    beds: int | None = None
    baths: int | None = None
    half_baths: int | None = None

    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    state_abbreviation: str | None = None
    zip_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    property_types: list[str] = Field(default_factory=list)
    description: str | None = None
    directions: str | None = None
    amenities: list[str] = Field(default_factory=list)

    mls_id: str | None = None
    listed_date: dt.date | None = None
    last_updated: str | None = None
    is_irrigated: bool | None = None
    has_residence: bool | None = None

    image_urls: list[str] = Field(default_factory=list)
    broker: Broker | None = None
    price_history: list[PriceEvent] = Field(default_factory=list)
