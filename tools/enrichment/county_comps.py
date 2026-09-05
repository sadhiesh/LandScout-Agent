"""County price comparables enricher.

Compares a parcel's price-per-acre against the county median by running
a broader LandWatch search for the same county.
"""

from __future__ import annotations

import logging
from typing import Any

from landwatch.models import SearchCriteria
from landwatch.search import search

from .registry import register

logger = logging.getLogger(__name__)


@register("county_comps", enabled=False)
def enrich_county_comps(parcel: dict[str, Any]) -> dict[str, Any]:
    """Enrich parcel with county-level price comparables.
    
    Runs a broader search for similar properties in the same county to
    compute median price-per-acre and compare against the target parcel.
    
    Args:
        parcel: Must include location.state, location.county, and
                basic_info.price_per_acre
        
    Returns:
        Dict with county median price-per-acre and comparison ratio
        
    Raises:
        ValueError: If required fields are missing
        Exception: If search fails
    """
    location = parcel.get("location", {})
    basic_info = parcel.get("basic_info", {})
    
    state = location.get("state")
    county = location.get("county")
    parcel_ppa = basic_info.get("price_per_acre")
    
    if not state or not county:
        raise ValueError(
            "parcel missing required location fields: state, county"
        )
    if parcel_ppa is None:
        raise ValueError(
            "parcel missing required basic_info field: price_per_acre"
        )
    
    logger.info(f"Fetching county comps for {county}, {state}")
    
    # Search for all land in the same county
    criteria = SearchCriteria(
        state=state,
        county=county,
        # No price/acres filters to get a representative sample
    )
    
    try:
        result = search(criteria)
        
        if not result.listings:
            logger.warning(f"No comparables found for {county}, {state}")
            return {
                "county_median_ppa": None,
                "comparison_ratio": None,
                "comp_count": 0,
            }
        
        # Calculate median price-per-acre from comparables
        ppas = [
            listing.price_per_acre
            for listing in result.listings
            if listing.price_per_acre is not None and listing.price_per_acre > 0
        ]
        
        if not ppas:
            logger.warning(
                f"No valid price-per-acre values in {county}, {state} comps"
            )
            return {
                "county_median_ppa": None,
                "comparison_ratio": None,
                "comp_count": len(result.listings),
            }
        
        ppas.sort()
        median_ppa = ppas[len(ppas) // 2]
        
        # Comparison ratio: parcel_ppa / median_ppa
        # <1.0 means below median (potential value)
        # >1.0 means above median (premium or overpriced)
        comparison_ratio = parcel_ppa / median_ppa if median_ppa > 0 else None
        
        logger.info(
            f"County median: ${median_ppa:.2f}/acre, "
            f"parcel: ${parcel_ppa:.2f}/acre, "
            f"ratio: {comparison_ratio:.2f}"
        )
        
        return {
            "county_median_ppa": median_ppa,
            "comparison_ratio": comparison_ratio,
            "comp_count": len(ppas),
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch county comps: {e}")
        raise
