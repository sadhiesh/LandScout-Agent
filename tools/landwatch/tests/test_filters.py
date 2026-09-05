"""Pin the filter catalog to LandWatch's own recorded facet list.

``tests/fixtures/search_texas_state.json`` is a state-level search response, whose
``filterSections`` array is LandWatch enumerating every facet it offers. Checking
the catalog against it means a value that gets added, renamed or re-numbered on
the site surfaces as a test failure the next time the fixture is refreshed,
rather than as a silently missing filter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from landwatch.filters import (
    FILTER_CATALOG,
    FilterKind,
    as_dict,
    coerce_value,
    describe,
    enumerable_filters,
)
from landwatch.models import SearchCriteria
from landwatch.vocab import (
    PROPERTY_TYPE_SLUGS,
    Activity,
    Geography,
    Hoa,
    HousingType,
    LandUse,
    MarketStatus,
    PropertyType,
    SaleType,
)

FIXTURE = Path(__file__).parent / "fixtures" / "search_texas_state.json"

# Place sections are dynamic per state and covered by test_places.py instead.
PLACE_SECTIONS = {"Region", "County", "City"}

# LandWatch's Availability links are toggle destinations rather than labels for
# their own segment: the default selection is available plus under-contract, so
# the link captioned "Available" points at the URL you reach by deselecting it,
# which carries only under-contract. Segment presence is still checked below;
# only the caption-to-segment pairing is skipped.
TOGGLE_SECTIONS = {"Availability"}


def _sections() -> list[dict]:
    return json.loads(FIXTURE.read_text())["filterSections"]


def _catalog_segments() -> dict[str, tuple[str, str, int | None]]:
    """Every segment the catalog can emit, mapped to (filter, label, id)."""
    segments: dict[str, tuple[str, str, int | None]] = {}
    for name, spec in FILTER_CATALOG.items():
        for value in list(spec.values) + list(spec.presets):
            segments.setdefault(value.segment, (name, value.label, value.id))
    return segments


def _har_links() -> list[tuple[str, dict]]:
    return [
        (section["section"], link)
        for section in _sections()
        if section["section"] not in PLACE_SECTIONS
        for link in section["filterLinks"]
    ]


def test_fixture_covers_every_section():
    """Guard the fixture itself: all 18 facet sections must be present."""
    sections = {section["section"] for section in _sections()}
    assert len(sections) == 18
    assert PLACE_SECTIONS <= sections


@pytest.mark.parametrize(("section", "link"), _har_links(), ids=lambda value: str(value)[:40])
def test_every_landwatch_value_is_in_the_catalog(section, link):
    segment = link["relativeUrlPath"].rstrip("/").rsplit("/", 1)[-1]
    segments = _catalog_segments()

    assert segment in segments, (
        f"LandWatch offers {section} / {link['displayText']!r} as segment {segment!r}, "
        "which the catalog does not know about"
    )

    _, label, identifier = segments[segment]
    if section not in TOGGLE_SECTIONS:
        assert label == link["displayText"]
    if link["id"]:
        assert identifier == link["id"], f"id drift for {segment}"


def test_every_section_maps_to_a_catalog_entry():
    sections = {section["section"] for section in _sections()}
    covered = {spec.section for spec in FILTER_CATALOG.values() if spec.section}
    assert sections <= covered, f"unmapped sections: {sections - covered}"


@pytest.mark.parametrize(
    ("enum_cls", "filter_name"),
    [
        (Activity, "activities"),
        (Geography, "geographies"),
        (Hoa, "hoa"),
        (HousingType, "housing_types"),
        (LandUse, "land_uses"),
        (MarketStatus, "market_statuses"),
        (SaleType, "sale_type"),
    ],
)
def test_catalog_values_match_their_enum(enum_cls, filter_name):
    """The catalog and the enums must describe the same value set.

    Compared as sets: the catalog lists values in LandWatch's display order,
    which need not match the enum's declaration order.
    """
    assert set(FILTER_CATALOG[filter_name].value_names) == {
        member.value for member in enum_cls
    }


def test_property_type_catalog_matches_the_enum():
    spec = FILTER_CATALOG["property_types"]
    assert {value.id for value in spec.values} == {
        int(member) for member in PropertyType.__members__.values()
    }
    assert {value.segment for value in spec.values} == set(PROPERTY_TYPE_SLUGS.values())


def test_catalog_counts_match_the_har():
    """The HAR's own tallies, as a guard against dropping a value."""
    expected = {
        "property_types": 13,
        "activities": 13,
        "geographies": 9,
        "land_uses": 6,
        "housing_types": 7,
        "hoa": 3,
        "sale_type": 2,
        "market_statuses": 4,
    }
    actual = {name: len(FILTER_CATALOG[name].values) for name in expected}
    assert actual == expected


def test_every_catalog_name_is_a_searchcriteria_field():
    """A filter nobody can set would be dead documentation."""
    fields = set(SearchCriteria.model_fields)
    # These are the range dimensions, which map to a _min/_max field pair.
    ranges = {"price", "acres", "sqft"}
    for name, spec in FILTER_CATALOG.items():
        if name in ranges:
            assert f"{name}_min" in fields and f"{name}_max" in fields
        else:
            assert name in fields, f"{name} ({spec.kind.value}) is not a SearchCriteria field"


def test_enumerable_filters_excludes_flags():
    enumerable = enumerable_filters()
    assert "geographies" in enumerable
    assert "owner_financing" not in enumerable, "booleans offer no choice of values"
    assert "has_residence" not in enumerable


def test_describe_renders_values_and_ids():
    text = describe("geographies")
    assert "geography-<value>" in text
    assert "off-grid" in text
    assert "1064" in text


def test_describe_rejects_unknown_filter():
    with pytest.raises(KeyError, match="unknown filter"):
        describe("nonexistent")


def test_as_dict_is_json_serialisable():
    payload = as_dict()
    assert json.loads(json.dumps(payload))["geographies"]["kind"] == FilterKind.MULTI_ENUM.value


@pytest.mark.parametrize(
    ("enum_cls", "text", "expected"),
    [
        # LandWatch labels this "Cabin" but slugs it "log-cabin", so both must work.
        (HousingType, "cabin", HousingType.CABIN),
        (HousingType, "Cabin", HousingType.CABIN),
        (HousingType, "log-cabin", HousingType.CABIN),
        (HousingType, "Lake House", HousingType.LAKE_HOUSE),
        (Activity, "Canoeing/Kayaking", Activity.CANOEING_KAYAKING),
        (Geography, "Off Grid", Geography.OFF_GRID),
        (Geography, "off_grid", Geography.OFF_GRID),
        (Hoa, "Yes (Mandatory)", Hoa.MANDATORY),
        (SaleType, "Auction", SaleType.AUCTION),
        (MarketStatus, "Under Contract", MarketStatus.UNDER_CONTRACT),
    ],
)
def test_coerce_accepts_values_and_labels(enum_cls, text, expected):
    assert coerce_value(enum_cls, text) is expected


def test_coerce_reports_valid_options():
    with pytest.raises(ValueError, match="unknown geographies 'swamp'"):
        coerce_value(Geography, "swamp")
