"""Test the model catalog loader and resolver."""

from __future__ import annotations

import pytest

from agents.common.model_catalog import (
    UnknownModelError,
    load_catalog,
    default_selection,
    resolve_selection,
)


def test_catalog_loads():
    """Catalog loads from config/models.yaml."""
    catalog = load_catalog()
    assert catalog.default_provider
    assert catalog.providers
    assert "eng_ai" in catalog.providers
    assert "openrouter" in catalog.providers


def test_default_selection():
    """Default selection resolves to first model of default provider."""
    selection = default_selection()
    assert selection.provider
    assert selection.model
    assert isinstance(selection.reasoning, bool)


def test_resolve_both_none_returns_default():
    """resolve_selection(None, None) returns the catalog default."""
    selection = resolve_selection(None, None)
    default = default_selection()
    assert selection.provider == default.provider
    assert selection.model == default.model


def test_resolve_provider_only():
    """Provider with None model returns first model of that provider."""
    selection = resolve_selection("eng_ai", None)
    assert selection.provider == "eng_ai"
    assert selection.model  # first model


def test_resolve_model_only_searches_all_providers():
    """Model with None provider searches all providers for that model."""
    catalog = load_catalog()
    # Pick first model of eng_ai
    eng_ai_model = catalog.providers["eng_ai"].models[0].id
    
    selection = resolve_selection(None, eng_ai_model)
    assert selection.model == eng_ai_model
    assert selection.provider == "eng_ai"


def test_resolve_both_provided_validates():
    """Provider + model validates the pair."""
    catalog = load_catalog()
    eng_ai_model = catalog.providers["eng_ai"].models[0].id
    
    selection = resolve_selection("eng_ai", eng_ai_model)
    assert selection.provider == "eng_ai"
    assert selection.model == eng_ai_model


def test_resolve_unknown_provider_raises():
    """Unknown provider raises UnknownModelError."""
    with pytest.raises(UnknownModelError, match="Unknown provider"):
        resolve_selection("nonexistent", None)


def test_resolve_unknown_model_raises():
    """Model not in any provider raises UnknownModelError."""
    with pytest.raises(UnknownModelError, match="not found in any provider"):
        resolve_selection(None, "nonexistent-model-id")


def test_resolve_model_not_in_provider_raises():
    """Model exists but not in specified provider raises UnknownModelError."""
    catalog = load_catalog()
    eng_ai_model = catalog.providers["eng_ai"].models[0].id
    
    with pytest.raises(UnknownModelError, match="not found in provider"):
        resolve_selection("openrouter", eng_ai_model)


def test_reasoning_flag_preserved():
    """Reasoning flag from catalog is preserved in selection."""
    catalog = load_catalog()
    
    # Find a reasoning model
    reasoning_model = None
    for provider_id, provider_entry in catalog.providers.items():
        for model_entry in provider_entry.models:
            if model_entry.reasoning:
                reasoning_model = (provider_id, model_entry.id)
                break
        if reasoning_model:
            break
    
    if reasoning_model:
        provider_id, model_id = reasoning_model
        selection = resolve_selection(provider_id, model_id)
        assert selection.reasoning is True
