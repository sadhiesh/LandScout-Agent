"""Parcel schema normalization.

Converts LandWatch's flat listing format to the canonical nested structure
used by scoring, memory, and UI. One home for the mapping.
"""

from __future__ import annotations

from typing import Any


def normalize_listing(flat: dict[str, Any]) -> dict[str, Any]:
    """Normalize a LandWatch flat listing to canonical nested structure.
    
    LandWatch returns flat keys (property_id, title, price, acres, city, county, etc).
    Our pipeline expects nested keys (property_id, location{}, basic_info{}).
    
    Args:
        flat: Flat listing dict from LandWatch run_search
        
    Returns:
        Normalized dict with location and basic_info nested blocks
    """
    # Calculate price_per_acre safely
    acres = flat.get("acres", 0)
    price = flat.get("price", 0)
    price_per_acre = (price / acres) if acres and acres > 0 else 0.0
    
    # Extract property types - could be a list or string
    property_types_raw = flat.get("property_types", [])
    if isinstance(property_types_raw, str):
        property_types = [property_types_raw]
    elif isinstance(property_types_raw, list):
        property_types = property_types_raw
    else:
        property_types = []
    
    return {
        "property_id": flat.get("property_id"),
        "listing_id": flat.get("listing_id"),
        "location": {
            "state": flat.get("state") or flat.get("state_abbreviation"),
            "county": flat.get("county"),
            "city": flat.get("city"),
            "zip_code": flat.get("zip_code"),
            "lat": flat.get("latitude"),
            "lon": flat.get("longitude"),
        },
        "basic_info": {
            "title": flat.get("title", "Untitled property"),
            "acres": acres,
            "price": price,
            "price_per_acre": price_per_acre,
            "url": flat.get("url", ""),
            "image_url": flat.get("image_url"),
            "property_types": property_types,
            "address": flat.get("address"),
            "beds": flat.get("beds"),
            "baths": flat.get("baths"),
            "broker": flat.get("broker"),
        },
        # Preserve any other top-level keys for debugging
        "_source": "landwatch",
    }
