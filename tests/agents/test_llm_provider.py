"""Test build_llm provider selection (offline, no network)."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from agents.common.llm import build_llm, _gateway_credentials, _openrouter_credentials


@pytest.fixture
def mock_gateway_key():
    """Mock the gateway key helper subprocess."""
    with patch("agents.common.llm.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="mock-gateway-key\n",
            stderr="",
        )
        yield mock_run


@pytest.fixture
def mock_openrouter_key(monkeypatch):
    """Mock the OpenRouter API key env var."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-mock-key")
    yield


def test_gateway_credentials_fetches_key(mock_gateway_key, monkeypatch):
    """_gateway_credentials calls the key helper and returns base_url + key."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    
    base_url, api_key = _gateway_credentials()
    
    assert base_url == "https://gateway.example.com/v1"
    assert api_key == "mock-gateway-key"
    mock_gateway_key.assert_called_once()


def test_gateway_credentials_missing_base_url_raises(monkeypatch):
    """_gateway_credentials raises if LLM_BASE_URL is not set."""
    monkeypatch.setenv("LLM_BASE_URL", "")
    
    with pytest.raises(RuntimeError, match="LLM_BASE_URL not configured"):
        _gateway_credentials()


def test_openrouter_credentials_returns_key(mock_openrouter_key):
    """_openrouter_credentials returns base_url + key from env."""
    base_url, api_key = _openrouter_credentials()
    
    assert base_url == "https://openrouter.ai/api/v1"
    assert api_key == "sk-or-mock-key"


def test_openrouter_credentials_missing_key_raises(monkeypatch):
    """_openrouter_credentials raises if OPENROUTER_API_KEY is not set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY not configured"):
        _openrouter_credentials()


def test_build_llm_eng_ai_provider(mock_gateway_key, monkeypatch):
    """build_llm with provider='eng_ai' uses gateway credentials."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    
    llm = build_llm(provider="eng_ai", model="claude-sonnet-5")
    
    # Verify it's a _NonStrictOpenAICompletion with the right base_url
    assert llm.base_url == "https://gateway.example.com/v1"
    assert llm.model == "claude-sonnet-5"


def test_build_llm_gateway_provider(mock_gateway_key, monkeypatch):
    """build_llm with provider='gateway' uses gateway credentials (legacy alias)."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    
    llm = build_llm(provider="gateway", model="claude-sonnet-5")
    
    # Verify it's a _NonStrictOpenAICompletion with the right base_url
    assert llm.base_url == "https://gateway.example.com/v1"
    assert llm.model == "claude-sonnet-5"


def test_build_llm_openrouter_provider(mock_openrouter_key, monkeypatch):
    """build_llm with provider='openrouter' uses OpenRouter credentials."""
    # Avoid gateway key fetch
    monkeypatch.setenv("LLM_BASE_URL", "")
    
    llm = build_llm(provider="openrouter", model="deepseek/deepseek-r1")
    
    assert llm.base_url == "https://openrouter.ai/api/v1"
    assert llm.model == "deepseek/deepseek-r1"


def test_build_llm_unknown_provider_raises():
    """build_llm with unknown provider raises after catalog resolution."""
    # The catalog resolver will raise UnknownModelError before we get to credentials
    from agents.common.model_catalog import UnknownModelError
    
    with pytest.raises(UnknownModelError, match="Unknown provider"):
        build_llm(provider="nonexistent", model="fake-model")


def test_build_llm_no_env_mutation(mock_gateway_key, mock_openrouter_key, monkeypatch):
    """build_llm does not mutate OPENAI_API_KEY or OPENAI_BASE_URL in os.environ."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    
    # Clear any existing values
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("OPENAI_BASE_URL", None)
    
    # Build LLM for eng_ai
    llm_gateway = build_llm(provider="eng_ai", model="claude-sonnet-5")
    
    # Verify no mutation
    assert os.environ.get("OPENAI_API_KEY") is None
    assert os.environ.get("OPENAI_BASE_URL") is None
    
    # Build LLM for OpenRouter
    llm_or = build_llm(provider="openrouter", model="deepseek/deepseek-r1")
    
    # Still no mutation
    assert os.environ.get("OPENAI_API_KEY") is None
    assert os.environ.get("OPENAI_BASE_URL") is None


def test_build_llm_defaults_to_env_provider_and_model(mock_gateway_key, monkeypatch):
    """build_llm with no args uses LLM_PROVIDER and LLM_MODEL from env."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.setenv("LLM_PROVIDER", "eng_ai")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5")
    
    llm = build_llm()
    
    assert llm.base_url == "https://gateway.example.com/v1"
    assert llm.model == "claude-sonnet-5"
