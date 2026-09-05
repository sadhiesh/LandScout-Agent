"""Place resolution tests, offline against the bundled dataset and a HAR fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from landwatch import places
from landwatch.models import SearchCriteria
from landwatch.places import Place, PlaceKind
from landwatch.url import build_path
from landwatch.vocab import STATE_ABBREVIATIONS, STATE_FIPS

AUTOCOMPLETE = Path(__file__).parent / "fixtures" / "autocomplete_texas.json"

requires_dataset = pytest.mark.skipif(
    not places.dataset_available(),
    reason="landwatch/data/geography.json not built; run scripts/build_geography.py",
)


@pytest.fixture(scope="module")
def autocomplete_places() -> list[Place]:
    return places.parse_autocomplete(json.loads(AUTOCOMPLETE.read_text()))


def test_state_tables_agree():
    assert set(STATE_ABBREVIATIONS) == set(STATE_FIPS)
    # The 50 states plus the District of Columbia, matching LandWatch's homepage.
    assert len(STATE_FIPS) == 51
    assert "dc" in STATE_FIPS


def test_state_ids_are_fips_codes():
    """Confirmed against the autocomplete endpoint's stateId values."""
    assert STATE_FIPS["tx"] == 48
    assert STATE_FIPS["co"] == 8
    assert STATE_FIPS["al"] == 1
    assert STATE_FIPS["il"] == 17


@pytest.mark.parametrize("query", ["tx", "TX", "texas", "Texas"])
def test_find_state_accepts_names_and_abbreviations(query):
    found = places.find_state(query)
    assert found is not None
    assert found.slug == "texas"
    assert found.landwatch_id == 48
    assert found.kind is PlaceKind.STATE


def test_find_state_rejects_unknown():
    assert places.find_state("Atlantis") is None


def test_list_states_is_complete():
    assert len(places.list_states()) == 51


def test_autocomplete_kinds(autocomplete_places):
    """LandWatch's numeric type: 1=city, 2=county, 5=region, 6=state."""
    kinds = {place.kind for place in autocomplete_places}
    assert kinds == {PlaceKind.STATE, PlaceKind.CITY, PlaceKind.COUNTY, PlaceKind.REGION}


def test_autocomplete_entries_of_unknown_type_are_dropped():
    assert places.parse_autocomplete([{"type": 99, "location": "Mystery"}]) == []


@pytest.mark.parametrize(
    ("name", "expected_slug", "expected_kind"),
    [
        # searchPath puts the suffixes in opposite orders: Grayson-County-TX
        # versus Houston-Texas-Region, so both orders must reduce correctly.
        ("Grayson County, TX", "grayson", PlaceKind.COUNTY),
        ("Montgomery County, TX", "montgomery", PlaceKind.COUNTY),
        ("Houston Texas Region", "houston", PlaceKind.REGION),
        ("Dallas Prairie Texas Region", "dallas-prairie", PlaceKind.REGION),
        ("Texas City, TX", "texas-city", PlaceKind.CITY),
        ("Texas, AL", "texas", PlaceKind.CITY),
        ("Texas", "texas", PlaceKind.STATE),
    ],
)
def test_autocomplete_slugs_are_bare_names(
    autocomplete_places, name, expected_slug, expected_kind
):
    match = next(place for place in autocomplete_places if place.name == name)
    assert match.slug == expected_slug
    assert match.kind is expected_kind


def test_autocomplete_slugs_are_usable_as_criteria(autocomplete_places):
    """The whole point of stripping suffixes: the slug must round-trip into a URL."""
    county = next(place for place in autocomplete_places if place.name == "Grayson County, TX")
    criteria = SearchCriteria(**county.criteria_kwargs())
    assert build_path(criteria) == "/texas-land-for-sale/grayson-county"

    region = next(place for place in autocomplete_places if place.name == "Houston Texas Region")
    assert build_path(SearchCriteria(**region.criteria_kwargs())) == (
        "/texas-land-for-sale/houston-region"
    )


def test_criteria_kwargs_for_state():
    assert places.find_state("tx").criteria_kwargs() == {"state": "texas"}


def test_criteria_kwargs_needs_a_state_for_subdivisions():
    orphan = Place(name="Nowhere County", slug="nowhere", kind=PlaceKind.COUNTY)
    with pytest.raises(ValueError, match="cannot be searched"):
        orphan.criteria_kwargs()


@requires_dataset
def test_texas_counties_are_complete():
    """Texas has 254 counties and LandWatch lists every one, untruncated."""
    assert len(places.list_counties("tx")) == 254


@requires_dataset
def test_rhode_island_counties():
    assert len(places.list_counties("ri")) == 5


@requires_dataset
def test_texas_regions():
    regions = {place.slug for place in places.list_regions("texas")}
    assert len(regions) == 29
    assert {"texoma", "hill-country-north", "panhandle"} <= regions


@requires_dataset
def test_region_and_county_lists_are_distinct():
    assert places.list_regions("tx") != places.list_counties("tx")


def test_list_places_for_unknown_state_is_empty():
    assert places.list_counties("Atlantis") == []


@requires_dataset
@pytest.mark.parametrize("query", ["grayson", "Grayson County", "GRAYSON"])
def test_resolve_finds_counties_offline(query):
    """Offline resolution must accept the natural phrasing, not just the slug."""
    found = places.resolve(query, kind=PlaceKind.COUNTY)
    assert {place.state for place in found} == {"KY", "TX", "VA"}
    assert all(place.slug == "grayson" for place in found)


@requires_dataset
def test_resolve_scoped_to_one_state():
    found = places.resolve("grayson", state="tx")
    assert len(found) == 1
    assert found[0].state == "TX"


@requires_dataset
def test_resolve_prefers_the_state_for_a_state_name():
    found = places.resolve("texas")
    assert found[0].kind is PlaceKind.STATE


@requires_dataset
def test_resolve_regions_offline():
    found = places.resolve("texoma")
    assert len(found) == 1
    assert found[0].kind is PlaceKind.REGION
    assert found[0].state == "TX"


def test_resolve_empty_query_does_not_hit_the_network():
    """A query of only punctuation has nothing to look up."""
    assert places._resolve_offline("!!!", kind=None, state=None) == []
