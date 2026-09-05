"""Configuration endpoints — read-only catalog and feature flags."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from agents.common import OPENROUTER_API_KEY
from agents.common.model_catalog import load_catalog

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config/models")
async def get_models() -> dict[str, Any]:
    """Get the LLM provider and model catalog.
    
    Returns the catalog from config/models.yaml plus per-provider availability flags.
    Read-only — no agent invocation, no live external call.
    
    Returns:
        Dict with:
            - default_provider: str
            - default_model: str (first model of default provider)
            - providers: dict of {provider_id: {label, available, models}}
    """
    catalog = load_catalog()
    
    # Build response with availability flags
    providers_response = {}
    for provider_id, provider_entry in catalog.providers.items():
        # Check if provider is available (has required credentials)
        available = True
        if provider_id == "openrouter":
            available = bool(OPENROUTER_API_KEY)
        
        providers_response[provider_id] = {
            "label": provider_entry.label,
            "available": available,
            "models": [
                {
                    "id": m.id,
                    "label": m.label,
                    "reasoning": m.reasoning,
                }
                for m in provider_entry.models
            ],
        }
    
    # Get default model (first model of default provider)
    default_provider_entry = catalog.providers.get(catalog.default_provider)
    default_model = (
        default_provider_entry.models[0].id
        if default_provider_entry and default_provider_entry.models
        else None
    )
    
    return {
        "default_provider": catalog.default_provider,
        "default_model": default_model,
        "providers": providers_response,
    }
