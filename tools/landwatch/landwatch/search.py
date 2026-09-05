"""High-level search API.

This is the layer most callers want::

    from landwatch import SearchCriteria, PropertyType, search

    result = search(SearchCriteria(
        state="texas",
        county="grayson",
        price_min=200_000,
        price_max=800_000,
        acres_min=5,
        acres_max=50,
        property_types=PropertyType.FARMS_AND_RANCHES | PropertyType.UNDEVELOPED,
    ))
    for listing in result.listings:
        print(listing.title, listing.price_display, listing.acres_display)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from .client import LandWatchClient
from .models import PropertyDetail, SearchCriteria, SearchResult
from .parse import parse_detail, parse_search
from .url import build_path

logger = logging.getLogger(__name__)


def search(
    criteria: SearchCriteria,
    *,
    client: LandWatchClient | None = None,
    validate: bool = False,
) -> SearchResult:
    """Fetch one page of listings matching ``criteria``.

    When ``validate`` is set, the constructed URL is also sent to LandWatch's
    criteria endpoint and any disagreement with the requested filters is logged
    as a warning. That guards against silent misreads if the URL grammar changes.
    """
    owns_client = client is None
    client = client or LandWatchClient()
    try:
        path = build_path(criteria)
        logger.debug("searching %s", path)
        payload = client.search_payload(path)
        result = parse_search(payload, criteria, path)
        if validate:
            _warn_on_mismatch(client, path, criteria)
        return result
    finally:
        if owns_client:
            client.close()


def search_all(
    criteria: SearchCriteria,
    *,
    max_pages: int = 10,
    max_listings: int | None = None,
    client: LandWatchClient | None = None,
) -> Iterator[SearchResult]:
    """Yield successive result pages, following LandWatch's own next-page links.

    Stops at ``max_pages``, when ``max_listings`` have been yielded, or when there
    is no next page.
    """
    owns_client = client is None
    client = client or LandWatchClient()
    seen = 0
    try:
        for offset in range(max_pages):
            page_criteria = criteria.model_copy(update={"page": criteria.page + offset})
            result = search(page_criteria, client=client)
            yield result

            seen += len(result.listings)
            if not result.listings or not result.has_next_page:
                return
            if max_listings is not None and seen >= max_listings:
                return
    finally:
        if owns_client:
            client.close()


def collect(
    criteria: SearchCriteria,
    *,
    max_pages: int = 10,
    max_listings: int | None = None,
    client: LandWatchClient | None = None,
) -> SearchResult:
    """Fetch up to ``max_pages`` of results and merge them into one SearchResult."""
    pages = list(
        search_all(criteria, max_pages=max_pages, max_listings=max_listings, client=client)
    )
    if not pages:
        raise ValueError("search returned no pages")

    merged = pages[0].model_copy(deep=True)
    for page in pages[1:]:
        merged.listings.extend(page.listings)
    if max_listings is not None:
        del merged.listings[max_listings:]
    merged.next_page_path = pages[-1].next_page_path
    return merged


def get_detail(
    property_id: int, *, client: LandWatchClient | None = None
) -> PropertyDetail:
    """Fetch full detail, including price history, for one listing."""
    owns_client = client is None
    client = client or LandWatchClient()
    try:
        return parse_detail(client.detail_payload(property_id))
    finally:
        if owns_client:
            client.close()


def _warn_on_mismatch(
    client: LandWatchClient, path: str, criteria: SearchCriteria
) -> None:
    """Compare our intent against LandWatch's reading of the same URL."""
    try:
        resolved = (client.criteria_payload(path) or {}).get("searchCriteria") or {}
    except Exception as exc:  # noqa: BLE001 - validation must never break a search
        logger.warning("could not validate %s: %s", path, exc)
        return

    checks = {
        "price_min": ("priceMin", criteria.price_min),
        "price_max": ("priceMax", criteria.price_max),
        "acres_min": ("acresMin", criteria.acres_min),
        "acres_max": ("acresMax", criteria.acres_max),
    }
    for label, (key, expected) in checks.items():
        if expected is None:
            continue
        actual = resolved.get(key)
        if actual is not None and float(actual) != float(expected):
            logger.warning(
                "LandWatch read %s as %s but %s was requested (path %s)",
                label,
                actual,
                expected,
                path,
            )

    if criteria.page != (resolved.get("pageIndex", 0) or 0) + 1:
        logger.warning(
            "LandWatch read page as %s but page %s was requested (path %s)",
            (resolved.get("pageIndex", 0) or 0) + 1,
            criteria.page,
            path,
        )
