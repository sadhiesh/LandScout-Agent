"""Enrichment registry and sources.

Import this module to register all enrichers and access the registry.
"""

from .cad_parcel import enrich_cad_parcel
from .county_comps import enrich_county_comps
from .flood_fema import enrich_flood_fema
from .landwatch_detail import enrich_landwatch_detail
from .registry import (
    REGISTRY,
    Enricher,
    get_enabled_enrichers,
    register,
    run_enrichment,
)
from .soil_usda import enrich_soil_usda
from .zoning import enrich_zoning

__all__ = [
    "REGISTRY",
    "Enricher",
    "get_enabled_enrichers",
    "register",
    "run_enrichment",
    "enrich_cad_parcel",
    "enrich_landwatch_detail",
    "enrich_county_comps",
    "enrich_flood_fema",
    "enrich_soil_usda",
    "enrich_zoning",
]
