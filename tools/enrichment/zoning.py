"""Zoning information enricher (STUB - disabled).

This enricher would query municipal or county zoning APIs to determine
permitted uses, setbacks, and building restrictions for a parcel.

Currently disabled. To enable:
1. Identify zoning data provider (e.g., Regrid, county GIS)
2. Obtain API key and implement zoning lookup by parcel ID or lat/lon
3. Add ZONING_API_KEY placeholder to config/.env.example
4. Write ADR in docs/decisions/ explaining rationale and provider choice
5. Set enabled=True in @register decorator below
"""

from __future__ import annotations

from typing import Any

from .registry import register


@register("zoning", enabled=False)
def enrich_zoning(parcel: dict[str, Any]) -> dict[str, Any]:
    """Enrich parcel with zoning information (STUB)."""
    raise NotImplementedError(
        "Zoning enricher is disabled. See tools/enrichment/zoning.py "
        "for implementation requirements."
    )
