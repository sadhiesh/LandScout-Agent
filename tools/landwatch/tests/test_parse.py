"""Parser tests, run entirely offline against fixtures captured from the HAR."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from landwatch.models import SearchCriteria
from landwatch.parse import image_url, parse_detail, parse_listing, parse_search
from landwatch.url import build_path
from landwatch.vocab import PropertyType

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def criteria() -> SearchCriteria:
    return SearchCriteria(
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


@pytest.fixture
def search_result(criteria):
    payload = load("search_texoma.json")
    return parse_search(payload, criteria, build_path(criteria))


def test_search_totals(search_result):
    assert search_result.total_count == 306
    # 306 listings at 25 per page.
    assert search_result.total_pages == 13
    assert search_result.page == 1
    assert search_result.location_name == "Texoma Region, TX"


def test_search_pagination(search_result):
    assert search_result.has_next_page
    assert search_result.next_page_path.endswith("/page-2")


def test_applied_filters_are_surfaced(search_result):
    assert "Texas" in search_result.applied_filters
    assert any("Texoma" in f for f in search_result.applied_filters)


def test_listing_core_fields(search_result):
    listing = search_result.listings[0]
    assert listing.property_id == 420918697
    assert listing.title == "14.22 Acres in Fannin County"
    assert listing.price == 170_000
    assert listing.price_display == "$170,000"
    assert listing.acres == 14.0
    assert listing.price_per_acre == pytest.approx(12142.86)
    assert listing.city == "Ladonia"
    assert listing.county == "Fannin County"
    assert listing.state_abbreviation == "TX"
    assert listing.zip_code == "75449"
    assert listing.latitude == pytest.approx(33.422305)
    assert listing.property_types == ["Farms and Ranches", "Hunting Property"]
    assert listing.url == (
        "https://www.landwatch.com/fannin-county-texas-farms-and-ranches-for-sale/pid/420918697"
    )


def test_listing_broker(search_result):
    broker = search_result.listings[0].broker
    assert broker is not None
    assert broker.name == "Sam McClellan"
    assert broker.company == "SAMMAC Farm and Ranch"
    assert broker.profile_url.startswith("https://www.landwatch.com/profile/")


def test_listing_images(search_result):
    listing = search_result.listings[0]
    assert listing.image_count == 7
    assert len(listing.image_urls) == 7
    assert listing.image_urls[0] == image_url(5836322973)
    assert "assets.landwatch.com" in listing.image_urls[0]


def test_zero_values_become_none(search_result):
    """LandWatch reports 0 for absent beds/baths/sqft on raw land."""
    listing = search_result.listings[0]
    assert listing.beds is None
    assert listing.baths is None
    assert listing.home_sqft is None


def test_sentinel_dates_become_none():
    """LandWatch uses 0001-01-01 to mean 'no date'."""
    listing = parse_listing(
        {
            "lwPropertyId": 1,
            "auctionDate": "0001-01-01T00:00:00",
            "onMarketDate": "0001-01-01T00:00:00",
            "lastUpdated": "0001-01-01T00:00:00",
        }
    )
    assert listing.listed_date is None
    assert listing.last_updated is None


def test_listing_dates_parsed(search_result):
    listing = search_result.listings[0]
    assert listing.listed_date is not None
    assert listing.listed_date.date() == date(2024, 9, 17)


def test_parser_tolerates_missing_fields():
    """A stripped-down payload must still parse rather than raise."""
    listing = parse_listing({"lwPropertyId": 42})
    assert listing.property_id == 42
    assert listing.title is None
    assert listing.price is None
    assert listing.property_types == []
    assert listing.image_urls == []
    assert listing.broker is None


def test_parser_tolerates_empty_search():
    result = parse_search({}, SearchCriteria(state="texas"), "/texas-land-for-sale")
    assert result.total_count == 0
    assert result.listings == []
    assert result.has_next_page is False


@pytest.fixture
def detail():
    return parse_detail(load("detail_422653962.json"))


def test_detail_core_fields(detail):
    assert detail.property_id == 422653962
    assert detail.title == "13.954 Acres"
    assert detail.price == 595_000.0
    assert detail.acres == pytest.approx(13.95)
    assert detail.address == "2554 Bennett Road"
    assert detail.city == "Howe"
    assert detail.county == "Grayson County"
    assert detail.state_abbreviation == "TX"
    assert detail.zip_code == "75459"
    assert detail.mls_id == "20908449"
    assert detail.listed_date == date(2025, 4, 18)
    assert detail.property_types == ["Recreational Property", "Undeveloped Land"]


def test_detail_description_joins_paragraphs(detail):
    assert detail.description
    assert "Bennett Road" in detail.description


def test_detail_price_history(detail):
    history = detail.price_history
    assert len(history) == 3
    assert history[0].event == "Price"
    assert history[0].date == date(2026, 7, 29)
    assert history[0].price == 595_000.0
    # Oldest entry is the original listing.
    assert history[-1].event == "Listed for Sale"
    assert history[-1].price == 699_000.0


def test_detail_broker(detail):
    assert detail.broker is not None
    assert detail.broker.company == "Butch Fife Realtors"


def test_detail_images(detail):
    assert len(detail.image_urls) == 16
    assert all(url.startswith("https://assets.landwatch.com/") for url in detail.image_urls)


def test_image_url_template():
    assert image_url(123, width=394, height=0) == (
        "https://assets.landwatch.com/resizedimages/394/0/h/80/1-123"
    )


def test_models_round_trip_json(search_result, detail):
    """Results must serialize cleanly, since that is how they leave the app."""
    restored = json.loads(search_result.model_dump_json())
    assert restored["total_count"] == 306
    assert restored["listings"][0]["property_id"] == 420918697

    restored_detail = json.loads(detail.model_dump_json())
    assert restored_detail["mls_id"] == "20908449"
    assert restored_detail["price_history"][0]["price"] == 595_000.0
