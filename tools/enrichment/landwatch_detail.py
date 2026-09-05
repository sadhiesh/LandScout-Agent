"""LandWatch detail enricher.

Wraps get_detail from tools/landwatch/ to fetch extended property information
including price history, days on market, full description, and amenities.
"""

from __future__ import annotations

import logging
from typing import Any

from landwatch.search import get_detail

from .registry import register

logger = logging.getLogger(__name__)


@register("landwatch_detail", enabled=True)
def enrich_landwatch_detail(parcel: dict[str, Any]) -> dict[str, Any]:
    """Enrich parcel with extended LandWatch detail.
    
    Fetches full property detail including:
    - Price history (list of date/price changes)
    - Days on market
    - Full description text
    - Property features and amenities
    - Utilities and access details
    
    Args:
        parcel: Must include 'property_id' field from search results
        
    Returns:
        Dict with enrichment facts
        
    Raises:
        ValueError: If property_id is missing
        Exception: If detail fetch fails
    """
    property_id = parcel.get("property_id")
    if not property_id:
        raise ValueError("parcel missing required field: property_id")
    
    logger.info(f"Fetching LandWatch detail for property {property_id}")
    
    detail = get_detail(int(property_id))
    
    return {
        "price_history": [
            {"date": h.date.isoformat(), "price": h.price}
            for h in (detail.price_history or [])
        ],
        "days_on_market": getattr(detail, "days_on_market", None),
        "description": detail.description,
        "full_location": {
            "city": detail.city,
            "county": detail.county,
            "state": detail.state_abbreviation,
            "zip": detail.zip_code,
        },
        "property_features": {
            "beds": detail.beds,
            "baths": detail.baths,
            "property_types": detail.property_types,
        },
        "broker": {
            "name": detail.broker.name,
            "phone": detail.broker.phone,
        }
        if detail.broker
        else None,
        "url": detail.url,
    }
