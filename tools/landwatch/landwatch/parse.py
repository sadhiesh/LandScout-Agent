"""Convert raw LandWatch JSON payloads into typed models.

Parsing is deliberately forgiving: these are undocumented internal endpoints, so
a renamed or missing field degrades one attribute to ``None`` rather than failing
the whole search.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from .models import (
    Broker,
    FacetOption,
    FacetSection,
    Listing,
    PriceEvent,
    PropertyDetail,
    SearchCriteria,
    SearchResult,
)
from .vocab import BASE_URL, RESULTS_PER_PAGE

# LandWatch renders images through a resizing service; height 0 means "auto".
# These URLs are the same ones LandWatch publishes in its own schema.org markup,
# so they load in a browser, but the asset host refuses non-browser clients. Treat
# them as links to show a user rather than URLs this app can download.
IMAGE_URL_TEMPLATE = "https://assets.landwatch.com/resizedimages/{width}/{height}/h/80/1-{doc_id}"

# Sentinel LandWatch uses for "no date".
_NULL_DATE_PREFIX = "0001-01-01"


def image_url(document_id: int, width: int = 800, height: int = 0) -> str:
    """Build a displayable image URL from a LandWatch document id."""
    return IMAGE_URL_TEMPLATE.format(width=width, height=height, doc_id=document_id)


def _clean_number(value: Any) -> Any:
    """Drop zero/NaN placeholders that LandWatch uses to mean "absent"."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        if value == 0:
            return None
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or value.startswith(_NULL_DATE_PREFIX):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    parsed = _parse_datetime(value)
    return parsed.date() if parsed else None


def _absolute(path: Any) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    return path if path.startswith("http") else BASE_URL + path


def _text(value: Any) -> str | None:
    """Normalize a string field, treating blanks as absent."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        joined = "\n\n".join(str(part).strip() for part in value if part)
        return joined or None
    return None


def _parse_facet_option(raw: dict[str, Any]) -> FacetOption | None:
    label = _text(raw.get("displayText"))
    if not label:
        return None
    count = raw.get("count")
    return FacetOption(
        label=label,
        count=int(count) if isinstance(count, (int, float)) else 0,
        relative_url_path=_text(raw.get("relativeUrlPath")),
        facet_id=int(raw["id"]) if isinstance(raw.get("id"), (int, float)) else None,
    )


def _parse_facet_sections(raw_sections: list[dict[str, Any]]) -> list[FacetSection]:
    sections: list[FacetSection] = []
    for raw_section in raw_sections:
        name = _text(raw_section.get("section"))
        if not name:
            continue
        options = [
            option
            for option in (
                _parse_facet_option(raw_option)
                for raw_option in (raw_section.get("filterLinks") or [])
                if isinstance(raw_option, dict)
            )
            if option is not None
        ]
        sections.append(FacetSection(section=name, options=options))
    return sections


def parse_listing(raw: dict[str, Any]) -> Listing:
    """Build a Listing from one ``searchResults.propertyResults`` entry."""
    broker = Broker(
        name=_text(raw.get("brokerName")),
        company=_text(raw.get("brokerCompany")),
        phone=_text(raw.get("brokerPhone")),
        profile_url=_absolute(raw.get("brokerCanonicalUrl")),
    )
    image_ids = raw.get("imageIds") or []

    return Listing(
        property_id=raw.get("lwPropertyId") or raw.get("siteListingId") or 0,
        listing_id=_clean_number(raw.get("id")),
        title=_text(raw.get("title")),
        url=_absolute(raw.get("canonicalUrl")),
        price=_clean_number(raw.get("price")),
        price_display=_text(raw.get("priceDisplay")),
        price_per_acre=_clean_number(raw.get("pricePerAcre")),
        price_change_amount=_clean_number(raw.get("priceChangeAmount")),
        price_change_percent=_clean_number(raw.get("priceChangePercentage")),
        acres=_clean_number(raw.get("acres")),
        acres_display=_text(raw.get("acresDisplay")),
        address=_text(raw.get("address")),
        city=_text(raw.get("city")),
        county=_text(raw.get("county")),
        state=_text(raw.get("state")),
        state_abbreviation=_text(raw.get("stateAbbreviation")),
        zip_code=_text(raw.get("zip")),
        latitude=_clean_number(raw.get("latitude")),
        longitude=_clean_number(raw.get("longitude")),
        property_types=[str(t) for t in (raw.get("types") or [])],
        beds=_clean_number(raw.get("beds")),
        baths=_clean_number(raw.get("baths")),
        home_sqft=_clean_number(raw.get("homesqft")),
        has_house=raw.get("hasHouse"),
        description=_text(raw.get("description")),
        image_count=raw.get("imageCount") or 0,
        image_urls=[image_url(doc_id) for doc_id in image_ids],
        broker=broker if any(broker.model_dump().values()) else None,
        listed_date=_parse_datetime(raw.get("onMarketDate") or raw.get("insertDate")),
        last_updated=_parse_datetime(raw.get("lastUpdated")),
    )


def parse_search(
    payload: dict[str, Any], criteria: SearchCriteria, path: str
) -> SearchResult:
    """Build a SearchResult from a raw search payload."""
    results = payload.get("searchResults") or {}
    pagination = results.get("paginationData") or {}
    total = results.get("totalCount") or 0
    listings = [parse_listing(item) for item in (results.get("propertyResults") or [])]

    applied = [
        text
        for text in (f.get("displayText", "").strip() for f in payload.get("activeFilters") or [])
        if text
    ]
    facets = _parse_facet_sections(payload.get("filterSections") or [])

    return SearchResult(
        criteria=criteria,
        url=BASE_URL + path,
        path=path,
        total_count=total,
        page=criteria.page,
        page_size=RESULTS_PER_PAGE,
        total_pages=max(1, math.ceil(total / RESULTS_PER_PAGE)) if total else 0,
        listings=listings,
        facets=facets,
        location_name=_text(pagination.get("locationName")),
        next_page_path=_text(pagination.get("nextLink")),
        applied_filters=applied,
    )


def parse_detail(payload: dict[str, Any]) -> PropertyDetail:
    """Build a PropertyDetail from a raw ``/api/property/{id}`` payload."""
    data = payload.get("propertyData") or {}
    address = data.get("address") or {}
    county = data.get("county") or {}
    state = data.get("state") or {}

    raw_broker = payload.get("brokerDetails") or {}
    broker = Broker(
        name=_text(raw_broker.get("contactName") or raw_broker.get("name")),
        company=_text(raw_broker.get("companyName") or raw_broker.get("company")),
        phone=_text(raw_broker.get("phone") or raw_broker.get("officePhone")),
        profile_url=_absolute(raw_broker.get("canonicalUrl")),
    )

    history = [
        PriceEvent(
            event=_text(event.get("eventTitle")) or "Unknown",
            date=_parse_date(event.get("date")),
            price=_clean_number(event.get("price")),
            price_change_percent=_clean_number(event.get("priceDelta")),
            acres=_clean_number(event.get("acres")),
        )
        for event in payload.get("listingEvents") or []
    ]

    amenities = [
        label
        for label in (
            _text(item.get("name") or item.get("displayText"))
            for item in payload.get("propertyAmenities") or []
            if isinstance(item, dict)
        )
        if label
    ]

    return PropertyDetail(
        property_id=data.get("siteListingId") or 0,
        listing_id=_clean_number(data.get("listingId")),
        title=_text(data.get("title")),
        url=_absolute(data.get("canonicalUrl")),
        price=_clean_number(data.get("price")),
        acres=_clean_number(data.get("acres")),
        home_sqft=_clean_number(data.get("homesqft")),
        beds=_clean_number(data.get("beds")),
        baths=_clean_number(data.get("baths")),
        half_baths=_clean_number(data.get("halfBaths")),
        address=_text(address.get("address1")),
        city=_text(address.get("city")) or _text((data.get("city") or {}).get("name")),
        county=_text(county.get("name")),
        state=_text(state.get("stateName")),
        state_abbreviation=_text(address.get("stateAbbreviation"))
        or _text(state.get("stateAbbreviation")),
        zip_code=_text(address.get("zip")),
        latitude=_clean_number(data.get("latitude")),
        longitude=_clean_number(data.get("longitude")),
        property_types=[str(t) for t in (data.get("types") or [])],
        description=_text(data.get("description")),
        directions=_text(data.get("directions")),
        amenities=amenities,
        mls_id=_text(data.get("mlsId")),
        listed_date=_parse_date(data.get("listingDate")),
        last_updated=_text(data.get("lastUpdated")),
        is_irrigated=data.get("isIrrigated"),
        has_residence=data.get("isResidence"),
        image_urls=[image_url(doc_id) for doc_id in data.get("imageDocumentIds") or []],
        broker=broker if any(broker.model_dump().values()) else None,
        price_history=history,
    )
