"""Build LandWatch search URL paths from structured criteria.

The path is a sequence of slash-separated filter segments in a fixed order, for
example::

    /texas-land-for-sale/texoma-region/prop-types-3683/price-100000-1000000/acres-10-30/page-2

Segment order matters: LandWatch treats the path as canonical and will not
resolve filters given in an arbitrary order. Every segment format here was
decoded from LandWatch's own filter links.
"""

from __future__ import annotations

from .models import SearchCriteria
from .vocab import BASE_URL, BOOLEAN_SEGMENTS, PropertyType, slugify, state_segment

# National search when no state is supplied.
NATIONAL_SEGMENT = "land"


def encode_property_types(types: PropertyType) -> int:
    """Encode property types as the integer LandWatch expects.

    Uses bitwise OR rather than addition because WATERFRONT (3584) already
    contains LAKEFRONT|OCEANFRONT|RIVERFRONT; summing would double-count them.
    """
    return int(types)


def _range_segment(prefix: str, low: float | None, high: float | None) -> str | None:
    """Render a numeric range segment, e.g. ``price-100000-1000000``.

    A one-sided range becomes ``<prefix>-under-<high>`` or ``<prefix>-over-<low>``.
    """
    if low is None and high is None:
        return None

    def fmt(value: float) -> str:
        # Acreage may be fractional, but whole numbers must not render as "10.0".
        return str(int(value)) if float(value).is_integer() else str(value)

    if low is not None and high is not None:
        return f"{prefix}-{fmt(low)}-{fmt(high)}"
    if high is not None:
        return f"{prefix}-under-{fmt(high)}"
    return f"{prefix}-over-{fmt(low)}"


def build_path(criteria: SearchCriteria) -> str:
    """Build the search URL path for ``criteria``.

    Returns a path beginning with ``/`` and without a trailing slash.
    """
    segments: list[str] = []

    if criteria.state:
        segments.append(state_segment(criteria.state))
    else:
        segments.append(NATIONAL_SEGMENT)

    # Geography. SearchCriteria guarantees at most one of these is set.
    if criteria.region:
        segments.append(f"{slugify(criteria.region)}-region")
    elif criteria.county:
        segments.append(f"{slugify(criteria.county)}-county")
    elif criteria.city:
        segments.append(slugify(criteria.city))

    if criteria.property_types:
        segments.append(f"prop-types-{encode_property_types(criteria.property_types)}")

    for status in criteria.market_statuses:
        segments.append(status.value)

    if criteria.has_residence is True:
        segments.append("with-residence")
    elif criteria.has_residence is False:
        segments.append("no-residence")

    for activity in criteria.activities:
        segments.append(f"{activity.value}-activity")

    for geography in criteria.geographies:
        segments.append(f"geography-{geography.value}")

    for land_use in criteria.land_uses:
        segments.append(f"present-use-{land_use.value}")

    for housing_type in criteria.housing_types:
        segments.append(f"housing-type-{housing_type.value}")

    if criteria.hoa:
        segments.append(criteria.hoa.value)

    if criteria.sale_type:
        segments.append(criteria.sale_type.value)

    for field, segment in BOOLEAN_SEGMENTS.items():
        if getattr(criteria, field):
            segments.append(segment)

    price = _range_segment("price", criteria.price_min, criteria.price_max)
    if price:
        segments.append(price)

    acres = _range_segment("acres", criteria.acres_min, criteria.acres_max)
    if acres:
        segments.append(acres)

    sqft = _range_segment("sqft", criteria.sqft_min, criteria.sqft_max)
    if sqft:
        segments.append(sqft)

    if criteria.beds_min:
        segments.append(f"beds-over-{criteria.beds_min}")
    if criteria.baths_min:
        segments.append(f"baths-over-{criteria.baths_min}")

    # Keyword follows the range segments, matching LandWatch's own URLs, e.g.
    # /texas-land-for-sale/texoma-region/price-under-1000000/keyword-undeveloped
    if criteria.keyword:
        segments.append(f"keyword-{slugify(criteria.keyword)}")

    if criteria.price_reduction_days:
        segments.append(f"price-reduction-{criteria.price_reduction_days}-days")

    if criteria.page > 1:
        segments.append(f"page-{criteria.page}")

    return "/" + "/".join(segments)


def build_url(criteria: SearchCriteria) -> str:
    """Build the public, browsable search URL for ``criteria``."""
    return BASE_URL + build_path(criteria)
