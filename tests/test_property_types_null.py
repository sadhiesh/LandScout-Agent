"""Tests for property_types=None handling in scoring."""

from __future__ import annotations

from tools.scoring.score_parcel import score_parcel


def test_criteria_with_null_property_types():
    """Test that None property_types in criteria doesn't crash scoring."""
    parcel = {
        "property_id": 1,
        "location": {"county": "Collin County", "city": "McKinney", "state": "TX"},
        "basic_info": {
            "acres": 15.5,
            "price": 500000,
            "price_per_acre": 32258,
            "property_types": ["Land"],
        },
    }
    
    enrichment = {}
    
    # This used to crash with TypeError: 'NoneType' object is not iterable
    criteria = {
        "acreage_min": 10.0,
        "acreage_max": 50.0,
        "price_min": 50000,
        "price_max": 800000,
        "property_types": None,  # Explicit None
    }
    
    result = score_parcel(parcel, enrichment, criteria)
    
    # Should not crash and should produce a valid score
    assert isinstance(result.total_score, float)
    assert 0 <= result.total_score <= 100


def test_parcel_with_null_property_types():
    """Test that None property_types in parcel doesn't crash scoring."""
    parcel = {
        "property_id": 1,
        "location": {"county": "Collin County", "city": "McKinney", "state": "TX"},
        "basic_info": {
            "acres": 15.5,
            "price": 500000,
            "price_per_acre": 32258,
            "property_types": None,  # Explicit None
        },
    }
    
    enrichment = {}
    
    criteria = {
        "acreage_min": 10.0,
        "acreage_max": 50.0,
        "price_min": 50000,
        "price_max": 800000,
        "property_types": ["Land"],
    }
    
    result = score_parcel(parcel, enrichment, criteria)
    
    # Should not crash and should produce a valid score
    assert isinstance(result.total_score, float)
    assert 0 <= result.total_score <= 100


def test_both_null_property_types():
    """Test that None property_types in both doesn't crash scoring."""
    parcel = {
        "property_id": 1,
        "location": {"county": "Collin County", "city": "McKinney", "state": "TX"},
        "basic_info": {
            "acres": 15.5,
            "price": 500000,
            "price_per_acre": 32258,
            "property_types": None,
        },
    }
    
    enrichment = {}
    
    criteria = {
        "acreage_min": 10.0,
        "acreage_max": 50.0,
        "price_min": 50000,
        "price_max": 800000,
        "property_types": None,
    }
    
    result = score_parcel(parcel, enrichment, criteria)
    
    # Should not crash and should produce a valid score
    assert isinstance(result.total_score, float)
    assert 0 <= result.total_score <= 100
