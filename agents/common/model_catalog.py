"""LLM provider and model catalog.

Single source of truth for selectable providers and models, loaded from
config/models.yaml. Nothing else may restate this vocabulary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class UnknownModelError(ValueError):
    """Raised when a provider or model is not in the catalog."""

    pass


class ModelEntry(BaseModel):
    """A single model in the catalog."""

    id: str
    label: str
    reasoning: bool = False


class ProviderEntry(BaseModel):
    """A provider and its models."""

    label: str
    models: list[ModelEntry]


class ModelCatalog(BaseModel):
    """The full catalog loaded from config/models.yaml."""

    default_provider: str
    providers: dict[str, ProviderEntry]


class LLMSelection(BaseModel):
    """A resolved provider + model selection."""

    provider: str
    model: str
    reasoning: bool


_CATALOG_PATH = Path(__file__).parent.parent.parent / "config" / "models.yaml"
_cached_catalog: ModelCatalog | None = None


def load_catalog() -> ModelCatalog:
    """Load the model catalog from config/models.yaml.

    Returns:
        Parsed catalog

    Raises:
        FileNotFoundError: If models.yaml doesn't exist
        yaml.YAMLError: If models.yaml is malformed
        pydantic.ValidationError: If the catalog structure is invalid
    """
    global _cached_catalog
    if _cached_catalog is not None:
        return _cached_catalog

    with _CATALOG_PATH.open() as f:
        raw = yaml.safe_load(f)

    _cached_catalog = ModelCatalog(**raw)
    return _cached_catalog


def default_selection() -> LLMSelection:
    """Get the default provider and model from the catalog.

    Returns:
        Default selection

    Raises:
        ValueError: If the default_provider or its first model doesn't exist
    """
    catalog = load_catalog()
    provider_id = catalog.default_provider

    if provider_id not in catalog.providers:
        raise ValueError(
            f"Default provider '{provider_id}' not found in catalog providers: "
            f"{list(catalog.providers.keys())}"
        )

    provider = catalog.providers[provider_id]
    if not provider.models:
        raise ValueError(f"Default provider '{provider_id}' has no models")

    model = provider.models[0]
    return LLMSelection(
        provider=provider_id, model=model.id, reasoning=model.reasoning
    )


def resolve_selection(
    provider: str | None, model: str | None
) -> LLMSelection:
    """Resolve a provider + model pair against the catalog.

    Args:
        provider: Provider ID (e.g., "gateway", "openrouter") or None for default
        model: Model ID or None for the provider's first model

    Returns:
        Resolved selection with reasoning flag

    Raises:
        UnknownModelError: If the provider or model is not in the catalog
    """
    catalog = load_catalog()

    # Default to catalog default if both are None
    if provider is None and model is None:
        return default_selection()

    # If only provider is given, default to its first model
    if provider is not None and model is None:
        if provider not in catalog.providers:
            raise UnknownModelError(
                f"Unknown provider '{provider}'. Available: {list(catalog.providers.keys())}"
            )
        provider_entry = catalog.providers[provider]
        if not provider_entry.models:
            raise UnknownModelError(f"Provider '{provider}' has no models")
        model_entry = provider_entry.models[0]
        return LLMSelection(
            provider=provider, model=model_entry.id, reasoning=model_entry.reasoning
        )

    # If only model is given, search all providers for it
    if provider is None and model is not None:
        for provider_id, provider_entry in catalog.providers.items():
            for model_entry in provider_entry.models:
                if model_entry.id == model:
                    return LLMSelection(
                        provider=provider_id,
                        model=model,
                        reasoning=model_entry.reasoning,
                    )
        raise UnknownModelError(
            f"Model '{model}' not found in any provider. "
            f"Check config/models.yaml for available models."
        )

    # Both provided: validate the pair
    if provider not in catalog.providers:
        raise UnknownModelError(
            f"Unknown provider '{provider}'. Available: {list(catalog.providers.keys())}"
        )

    provider_entry = catalog.providers[provider]
    for model_entry in provider_entry.models:
        if model_entry.id == model:
            return LLMSelection(
                provider=provider, model=model, reasoning=model_entry.reasoning
            )

    raise UnknownModelError(
        f"Model '{model}' not found in provider '{provider}'. "
        f"Available models: {[m.id for m in provider_entry.models]}"
    )
