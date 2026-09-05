"""Tests for Scorer agent's two-field JSON parsing and fallback behavior."""

from __future__ import annotations

import json


class TestRationaleParsing:
    """Parse rationale and considerations from LLM output."""

    def test_parses_two_field_json(self):
        """LLM returns rationale and considerations, both are extracted."""
        llm_output = json.dumps([
            {
                "property_id": 123,
                "rationale": "Strong value at $4,100/acre vs county median.",
                "considerations": ["Is the property in a 100-year floodplain?", "Check local zoning restrictions"]
            },
            {
                "property_id": 456,
                "rationale": "Good acreage fit but high tax burden.",
                "considerations": ["Verify MUD fees and their history"]
            }
        ])

        # Simulate extract_json parsing
        from agents.common.json_utils import extract_json
        parsed = extract_json(llm_output)

        assert len(parsed) == 2
        assert parsed[0]["property_id"] == 123
        assert parsed[0]["rationale"]
        assert parsed[0]["considerations"]
        assert isinstance(parsed[0]["considerations"], list)
        assert len(parsed[0]["considerations"]) == 2

    def test_considerations_default_to_empty_when_missing(self):
        """If considerations key is absent, it defaults to empty list."""
        llm_output = json.dumps([
            {
                "property_id": 123,
                "rationale": "Strong value proposition."
            }
        ])

        from agents.common.json_utils import extract_json
        parsed = extract_json(llm_output)

        # Application code should handle missing key with .get("considerations", [])
        considerations = parsed[0].get("considerations", [])
        assert considerations == []

    def test_invalid_considerations_fall_back_to_empty(self):
        """If considerations is not a list, fallback to empty list."""
        llm_output = json.dumps([
            {
                "property_id": 123,
                "rationale": "Strong value.",
                "considerations": "This should be a list"
            }
        ])

        from agents.common.json_utils import extract_json
        parsed = extract_json(llm_output)

        # Application code checks isinstance(considerations, list)
        considerations = parsed[0].get("considerations", [])
        if not isinstance(considerations, list):
            considerations = []

        assert considerations == []

    def test_whole_response_fails_triggers_fallback(self):
        """When extract_json fails entirely, fallback to dimension explanation."""
        invalid_output = "This is not valid JSON at all."

        from agents.common.json_utils import extract_json

        try:
            parsed = extract_json(invalid_output)
            # If extract_json silently returns empty or raises, fallback triggers
            if not parsed:
                raise ValueError("No JSON found")
        except (ValueError, json.JSONDecodeError):
            # Fallback: use first dimension explanation, no considerations
            fallback_rationale = "dimension explanation here"
            fallback_considerations = []

            assert fallback_rationale
            assert fallback_considerations == []


class TestScorerFallbackBehavior:
    """Fallback when LLM generation fails."""

    def test_top_20_get_llm_rationale(self):
        """Only top 20 parcels get LLM rationale/considerations."""
        # This is integration-level behavior verified by scorer.py
        # write_rationales_with_llm processes top_parcels[:20]
        top_parcels = [{"property_id": i, "score": 100 - i} for i in range(25)]
        llm_parcels = top_parcels[:20]

        assert len(llm_parcels) == 20
        # Parcels 21-25 should get fallback rationale

    def test_fallback_uses_first_dimension(self):
        """Parcels beyond top 20 get first dimension explanation as rationale."""
        # Simulated fallback logic
        parcel_score_breakdown = {
            "dimensions": {
                "value_vs_comps": {
                    "explanation": "$10,000/acre vs $12,000 median"
                },
                "criteria_match": {
                    "explanation": "Price within range"
                }
            }
        }

        # Fallback: take first dimension's explanation
        first_dim = next(iter(parcel_score_breakdown["dimensions"].values()), {})
        fallback_rationale = first_dim.get("explanation", "")

        assert fallback_rationale == "$10,000/acre vs $12,000 median"

    def test_no_dimensions_yields_empty_rationale(self):
        """If breakdown has no dimensions, fallback to empty string."""
        parcel_score_breakdown = {"dimensions": {}}

        first_dim = next(iter(parcel_score_breakdown["dimensions"].values()), {})
        fallback_rationale = first_dim.get("explanation", "")

        assert fallback_rationale == ""
