"""USDA soil quality enricher (STUB - disabled).

This enricher would query USDA's Web Soil Survey to fetch soil composition
and agricultural productivity ratings for a parcel.

Currently disabled. To enable:
1. Identify USDA Web Soil Survey API or data service endpoint
2. Implement soil data fetch by lat/lon or parcel boundary
3. Add any required API keys to config/.env.example
4. Write ADR in docs/decisions/ explaining rationale for enabling
5. Set enabled=True in @register decorator below
"""

from __future__ import annotations

from typing import Any

from .registry import register


@register("soil_usda", enabled=False)
def enrich_soil_usda(parcel: dict[str, Any]) -> dict[str, Any]:
    """Enrich parcel with USDA soil quality data (STUB)."""
    raise NotImplementedError(
        "USDA soil enricher is disabled. See tools/enrichment/soil_usda.py "
        "for implementation requirements."
    )
