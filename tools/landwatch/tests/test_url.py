"""URL grammar tests.

The expected paths here were taken from a recorded LandWatch browsing session and
confirmed against the live site, so they act as a regression guard on the grammar.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from landwatch.models import SearchCriteria
from landwatch.url import build_path, build_url
from landwatch.vocab import (
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


def test_reproduces_recorded_keyword_path():
    """The keyword URL recorded in the HAR, reproduced byte for byte.

    Also pins keyword's position after the range segments.
    """
    criteria = SearchCriteria(
        state="texas", region="texoma", price_max=1_000_000, keyword="undeveloped"
    )
    assert build_path(criteria) == (
        "/texas-land-for-sale/texoma-region/price-under-1000000/keyword-undeveloped"
    )


def test_keyword_is_slugified():
    criteria = SearchCriteria(state="texas", keyword="Creek Frontage")
    assert build_path(criteria).endswith("/keyword-creek-frontage")


def test_keyword_without_searchable_characters_rejected():
    """A punctuation-only keyword would otherwise emit a bare 'keyword-' segment."""
    with pytest.raises(ValidationError, match="no searchable characters"):
        SearchCriteria(state="texas", keyword="!!!")


def test_geography_segments():
    criteria = SearchCriteria(
        state="colorado", geographies=[Geography.MOUNTAIN, Geography.OFF_GRID]
    )
    segments = build_path(criteria).split("/")
    assert "geography-mountain" in segments
    assert "geography-off-grid" in segments


def test_sale_type_segment():
    assert "auctions" in build_path(SearchCriteria(state="texas", sale_type=SaleType.AUCTION))
    assert "for-sale" in build_path(SearchCriteria(state="texas", sale_type=SaleType.FOR_SALE))


def test_newly_decoded_property_types():
    """Timberland and Homesite were absent from the first HAR's facet list."""
    assert build_path(SearchCriteria(state="maine", property_types=PropertyType.TIMBERLAND)) == (
        "/maine-land-for-sale/prop-types-16"
    )
    combined = PropertyType.TIMBERLAND | PropertyType.HOMESITE
    assert int(combined) == 4112
    assert build_path(SearchCriteria(state="maine", property_types=combined)).endswith(
        "prop-types-4112"
    )


def test_voluntary_hoa_segment():
    assert build_path(SearchCriteria(state="texas", hoa=Hoa.VOLUNTARY)).endswith("hoa-voluntary")


def test_reproduces_recorded_path():
    """The exact path observed in the HAR must be reproduced byte for byte."""
    criteria = SearchCriteria(
        state="texas",
        region="texoma",
        price_min=100_000,
        price_max=1_000_000,
        acres_min=10,
        acres_max=30,
        property_types=(
            PropertyType.FARMS_AND_RANCHES
            | PropertyType.UNDEVELOPED
            | PropertyType.COMMERCIAL
            | PropertyType.WATERFRONT
        ),
    )
    assert build_path(criteria) == (
        "/texas-land-for-sale/texoma-region/prop-types-3683"
        "/price-100000-1000000/acres-10-30"
    )


def test_property_types_use_bitwise_or_not_sum():
    """WATERFRONT overlaps its three constituents, so OR and sum diverge.

    Summing {3, 32, 64, 512, 1024, 2048, 3584} gives 7267; LandWatch expects 3683.
    """
    combined = (
        PropertyType.FARMS_AND_RANCHES
        | PropertyType.UNDEVELOPED
        | PropertyType.COMMERCIAL
        | PropertyType.LAKEFRONT
        | PropertyType.OCEANFRONT
        | PropertyType.RIVERFRONT
        | PropertyType.WATERFRONT
    )
    assert int(combined) == 3683

    naive_sum = 3 + 32 + 64 + 512 + 1024 + 2048 + 3584
    assert naive_sum == 7267
    assert int(combined) != naive_sum


def test_waterfront_absorbs_its_constituents():
    assert int(PropertyType.WATERFRONT | PropertyType.LAKEFRONT) == 3584


def test_single_type_encoding():
    criteria = SearchCriteria(state="colorado", property_types=PropertyType.HUNTING)
    assert build_path(criteria) == "/colorado-land-for-sale/prop-types-128"


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        (
            SearchCriteria(state="TX", county="grayson", price_min=200_000, price_max=800_000,
                           acres_min=5, acres_max=50),
            "/texas-land-for-sale/grayson-county/price-200000-800000/acres-5-50",
        ),
        (
            SearchCriteria(state="tennessee", owner_financing=True, acres_min=20, acres_max=100),
            "/tennessee-land-for-sale/owner-financing/acres-20-100",
        ),
        (
            SearchCriteria(state="texas", city="howe"),
            "/texas-land-for-sale/howe",
        ),
        (
            SearchCriteria(state="colorado", property_types=PropertyType.HUNTING,
                           acres_min=40, acres_max=500, page=2),
            "/colorado-land-for-sale/prop-types-128/acres-40-500/page-2",
        ),
    ],
)
def test_verified_paths(criteria, expected):
    """Paths that were each confirmed to return HTTP 200 from the live endpoint."""
    assert build_path(criteria) == expected


def test_state_abbreviation_and_name_agree():
    assert build_path(SearchCriteria(state="TX")) == build_path(SearchCriteria(state="texas"))


def test_national_search_without_state():
    assert build_path(SearchCriteria()) == "/land"
    assert build_path(SearchCriteria(price_max=50_000)) == "/land/price-under-50000"


def test_one_sided_ranges():
    assert build_path(SearchCriteria(state="texas", acres_min=40)).endswith("acres-over-40")
    assert build_path(SearchCriteria(state="texas", acres_max=40)).endswith("acres-under-40")
    assert build_path(SearchCriteria(state="texas", price_min=250_000)).endswith("price-over-250000")


def test_whole_numbers_do_not_render_as_floats():
    """acres_min=10.0 must render as 'acres-10', not 'acres-10.0'."""
    assert build_path(SearchCriteria(state="texas", acres_min=10.0, acres_max=30.0)).endswith(
        "acres-10-30"
    )


def test_fractional_acres_are_preserved():
    assert build_path(SearchCriteria(state="texas", acres_min=2.5)).endswith("acres-over-2.5")


def test_page_one_is_implicit():
    assert "page-" not in build_path(SearchCriteria(state="texas", page=1))
    assert build_path(SearchCriteria(state="texas", page=3)).endswith("/page-3")


def test_facet_segments():
    criteria = SearchCriteria(
        state="florida",
        activities=[Activity.FISHING],
        land_uses=[LandUse.HOMESTEAD],
        housing_types=[HousingType.BARNDOMINIUM],
        hoa=Hoa.NONE,
        market_statuses=[MarketStatus.AVAILABLE],
        beds_min=3,
        baths_min=2,
    )
    path = build_path(criteria)
    for segment in (
        "available",
        "fishing-activity",
        "present-use-homestead",
        "housing-type-barndominium",
        "hoa-none",
        "beds-over-3",
        "baths-over-2",
    ):
        assert segment in path.split("/"), f"missing {segment} in {path}"


def test_residence_toggle():
    assert "with-residence" in build_path(SearchCriteria(state="texas", has_residence=True))
    assert "no-residence" in build_path(SearchCriteria(state="texas", has_residence=False))
    assert "residence" not in build_path(SearchCriteria(state="texas"))


def test_price_reduction_segment():
    criteria = SearchCriteria(state="texas", price_reduction_days=90)
    assert build_path(criteria).endswith("price-reduction-90-days")


def test_build_url_is_absolute():
    assert build_url(SearchCriteria(state="texas")) == (
        "https://www.landwatch.com/texas-land-for-sale"
    )


def test_geography_is_mutually_exclusive():
    with pytest.raises(ValidationError, match="only one of region/county/city"):
        SearchCriteria(state="texas", county="grayson", city="howe")


def test_geography_requires_state():
    with pytest.raises(ValidationError, match="requires 'state'"):
        SearchCriteria(county="grayson")


def test_inverted_ranges_rejected():
    with pytest.raises(ValidationError, match="price_min must not exceed price_max"):
        SearchCriteria(state="texas", price_min=900_000, price_max=100_000)
    with pytest.raises(ValidationError, match="acres_min must not exceed acres_max"):
        SearchCriteria(state="texas", acres_min=90, acres_max=10)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Grayson County", "grayson-county"),
        ("St. Mary's", "st-marys"),
        ("Miami-Dade", "miami-dade"),
        ("  Honey  Grove ", "honey-grove"),
        ("Doña Ana", "dona-ana"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_segment_order_is_canonical():
    """Place precedes types, which precede ranges, then keyword, then page."""
    criteria = SearchCriteria(
        state="texas",
        county="grayson",
        property_types=PropertyType.HUNTING,
        geographies=[Geography.RURAL],
        price_min=100_000,
        acres_min=10,
        keyword="creek",
        page=2,
    )
    segments = build_path(criteria).strip("/").split("/")
    assert segments[0] == "texas-land-for-sale"
    assert segments[1] == "grayson-county"
    assert segments[2] == "prop-types-128"
    assert segments[-1] == "page-2"
    assert segments.index("geography-rural") < segments.index("price-over-100000")
    assert segments.index("price-over-100000") < segments.index("acres-over-10")
    assert segments.index("acres-over-10") < segments.index("keyword-creek")
