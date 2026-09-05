"""Test that _score_land_use_fit handles null property_types."""

from __future__ import annotations

from tools.scoring.score_parcel import score_parcel


def test_land_use_fit_with_null_property_types():
    """Test that null property_types in criteria doesn't crash _score_land_use_fit."""
    parcel = {
        "property_id": 427307927,
        "location": {"county": "Collin County", "city": "McKinney", "state": "TX"},
        "basic_info": {
            "acres": 15.5,
            "price": 500000,
            "price_per_acre": 32258,
            "property_types": ["Land"],
        },
    }
    
    # CAD enrichment with land classification
    enrichment = {
        "cad_parcel": {
            "parcel_id": "R-123-456",
            "land": {
                "landTypeCode": "D1",
                "landCategoryCodes": "D1,E",
            },
            "improved": False,
        }
    }
    
    # This used to crash at line 523 with TypeError: 'NoneType' object is not iterable
    criteria = {
        "acreage_min": 10.0,
        "acreage_max": 50.0,
        "price_min": 50000,
        "price_max": 800000,
        "property_types": None,  # Explicit None
    }
    
    result = score_parcel(parcel, enrichment, criteria)
    
    # Should not crash and should produce a valid score
    # (The key fix is that it doesn't raise TypeError: 'NoneType' object is not iterable)
    assert isinstance(result.total_score, float)
    assert 0 <= result.total_score <= 100
