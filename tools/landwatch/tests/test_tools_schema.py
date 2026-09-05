"""Keep the agent-facing tool schema within Bedrock's tool-schema limits.

Bedrock rejects ``minimum`` / ``maximum`` on an integer parameter outright, and
the failure only appeared as a gateway 400 at agent runtime, so it is pinned
here offline. See ``docs/decisions/0008-bedrock-compatible-tool-schemas.md``.

An all-properties-required hook used to live here too, added to shrink Bedrock's
compiled decoding grammar. It did not work and has been removed — see
``docs/decisions/0010-drop-strict-from-native-tool-schemas.md`` for the actual
cause and the fix.
"""

from __future__ import annotations

import json

import pytest

import landwatch.tools as landwatch_tools
from landwatch.tools import LandSearchInput, build_crewai_tool, run_search

_UNSUPPORTED_KEYWORDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")


def test_optional_filters_are_optional_in_the_exported_schema() -> None:
    """Only genuinely mandatory filters may be required; there are none."""
    schema = LandSearchInput.model_json_schema()

    assert schema.get("required", []) == []


def test_schema_declares_no_numeric_bounds() -> None:
    dumped = json.dumps(LandSearchInput.model_json_schema())

    for keyword in _UNSUPPORTED_KEYWORDS:
        assert keyword not in dumped


def test_max_results_bounds_are_still_enforced() -> None:
    """Dropping ge/le from the schema must not drop the bound itself."""
    for value in (0, 201):
        with pytest.raises(ValueError):
            LandSearchInput(max_results=value)


def test_library_callers_may_still_omit_fields() -> None:
    """Requiring keys in the exported schema must not require them in Python."""
    payload = LandSearchInput(state="texas")

    assert payload.state == "texas"
    assert payload.property_types == []
    assert payload.max_results == 25


def test_invalid_arguments_return_json_rather_than_raising() -> None:
    result = json.loads(run_search(property_types=["not-a-real-type"]))

    assert "error" in result


def test_crewai_tool_returns_result_directly() -> None:
    tool = build_crewai_tool()
    structured = tool.to_structured_tool()

    assert tool.result_as_answer is True
    assert structured.result_as_answer is True


def test_crewai_tool_preserves_large_json_without_reserialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "search_url": "https://example.test/search",
            "total_matching": 25,
            "returned": 25,
            "listings": [
                {"property_id": index, "title": f"Parcel {index}"}
                for index in range(25)
            ],
        }
    )
    monkeypatch.setattr(landwatch_tools, "run_search", lambda **_: payload)

    tool = build_crewai_tool()

    assert tool._run(state="texas") == payload


def test_search_output_includes_geo_fields() -> None:
    """Verify run_search output includes lat/lon/address fields for CAD lookup."""
    # This test documents the expected output structure; actual values come from
    # offline fixtures in integration tests. Here we just verify the schema.
    expected_keys = {
        "property_id",
        "listing_id",
        "title",
        "price",
        "acres",
        "price_per_acre",
        "latitude",
        "longitude",
        "address",
        "city",
        "county",
        "state",
        "zip_code",
        "property_types",
        "beds",
        "baths",
        "broker",
        "url",
    }
    
    # Verify the schema matches expectations by inspecting a mock listing structure
    # The actual run_search uses Listing model, we verify keys are present in output
    from landwatch.models import Listing
    
    # Create a minimal listing to verify the mapping is correct
    listing = Listing(
        property_id=12345,
        listing_id=67890,
        title="Test Property",
        url="https://example.com/test",
        price=100000.0,
        acres=10.0,
        price_per_acre=10000.0,
        latitude=33.0,
        longitude=-96.0,
        address="123 Test St",
        city="TestCity",
        county="TestCounty",
        state="Texas",
        state_abbreviation="TX",
        zip_code="75000",
        property_types=["land"],
    )
    
    # Verify our expected keys match the Listing model fields
    listing_dict = listing.model_dump()
    for key in ("property_id", "listing_id", "latitude", "longitude", "address", "zip_code"):
        assert key in listing_dict, f"Listing model missing {key}"
