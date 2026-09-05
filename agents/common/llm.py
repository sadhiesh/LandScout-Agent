"""LLM factory for CrewAI agents using the gateway's OpenAI-compatible endpoint."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from typing import Any, Optional

from crewai.llms.base_llm import BaseLLM
from crewai.llms.providers.openai.completion import OpenAICompletion
from openai import AuthenticationError
import certifi

from .config import (
    LLM_BASE_URL,
    LLM_KEY_HELPER,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_CALL_TIMEOUT,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)

logger = logging.getLogger(__name__)

_cached_key: Optional[str] = None


class _NonStrictOpenAICompletion(OpenAICompletion):
    """OpenAI provider that omits ``strict`` from native tool schemas.

    CrewAI hardcodes ``strict: True`` on every tool it sends. Bedrock turns a
    strict schema into a constrained-decoding grammar sized exponentially in
    the property count, because JSON members may arrive in any order and the
    grammar tracks which keys were already emitted. ``landwatch_search``'s 22
    properties compile to 343.9MB against a 300MB cap and the gateway returns
    400. Marking properties required does not help — it does not constrain
    order. Arguments are still validated by each tool's Pydantic input model.
    """

    def _convert_tools_for_interference(
        self, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        converted = super()._convert_tools_for_interference(tools)
        for tool in converted:
            tool.get("function", {}).pop("strict", None)
        return converted
    
    def call(self, *args, **kwargs):
        """Override call to add timing instrumentation."""
        start = time.time()
        logger.info("🔄 LLM call started...")
        try:
            result = super().call(*args, **kwargs)
            duration = (time.time() - start) * 1000
            logger.info(f"✓ LLM call completed in {duration:.0f}ms ({duration/1000:.1f}s)")
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(f"✗ LLM call failed after {duration:.0f}ms: {e}")
            raise


def _fetch_gateway_key() -> str:
    """Fetch the short-lived gateway key via the helper command.
    
    Raises:
        RuntimeError: If the helper command fails or returns empty output.
    """
    if not LLM_KEY_HELPER:
        raise RuntimeError(
            "LLM_KEY_HELPER not configured. Set it in .env or config/.env.example."
        )
    
    try:
        result = subprocess.run(
            shlex.split(LLM_KEY_HELPER),
            capture_output=True,
            text=True,
            check=True,
            timeout=LLM_CALL_TIMEOUT,
        )
        key = result.stdout.strip()
        if not key:
            raise RuntimeError(f"Helper returned empty output: {LLM_KEY_HELPER}")
        return key
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to fetch gateway key via {LLM_KEY_HELPER}: {e.stderr}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Helper command not found: {LLM_KEY_HELPER}. "
            "Update LLM_KEY_HELPER in your .env file."
        ) from e


def _gateway_credentials() -> tuple[str, str]:
    """Get credentials for the Salesforce gateway.
    
    Returns:
        Tuple of (base_url, api_key)
        
    Raises:
        RuntimeError: If base URL is not configured or key fetch fails
    """
    global _cached_key
    
    if not LLM_BASE_URL:
        raise RuntimeError(
            "LLM_BASE_URL not configured. Set it in .env or config/.env.example."
        )
    
    # Fetch key if not cached
    if _cached_key is None:
        logger.info("Fetching gateway key at process start")
        _cached_key = _fetch_gateway_key()
    
    return (f"{LLM_BASE_URL}/v1", _cached_key)


def _openrouter_credentials() -> tuple[str, str]:
    """Get credentials for OpenRouter.
    
    Returns:
        Tuple of (base_url, api_key)
        
    Raises:
        RuntimeError: If OPENROUTER_API_KEY is not configured
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY not configured. Set it in your .env file "
            "(copy config/.env.example and add your key)."
        )
    
    return (OPENROUTER_BASE_URL, OPENROUTER_API_KEY)


def build_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    refetch_on_auth_failure: bool = True,
) -> BaseLLM:
    """Build a CrewAI LLM configured for the selected provider.
    
    Supports both the Engineering AI gateway (eng_ai/gateway) and OpenRouter. Uses CrewAI 1.15's native
    OpenAI transport (_NonStrictOpenAICompletion) for both, since OpenRouter is
    OpenAI-compatible and we need to strip the `strict` flag from tool schemas
    (ADR 0010) for both providers.
    
    ⚠️  SSL Verification (gateway only):
    The Salesforce gateway uses an internal CA certificate. To work around SSL errors:
    - Option 1 (RECOMMENDED): Get the Salesforce CA cert from IT and add to system trust
    - Option 2 (DEVELOPMENT ONLY): Set environment variable DISABLE_SSL_VERIFY=true
    
    Args:
        provider: Provider ID ("eng_ai", "gateway" or "openrouter"), or None for LLM_PROVIDER env
        model: Model identifier, or None for LLM_MODEL env
        temperature: Sampling temperature
        refetch_on_auth_failure: If True, refetch gateway key once on auth error
    
    Returns:
        Configured LLM instance
    
    Raises:
        RuntimeError: If credentials are missing or key fetch fails
        UnknownModelError: If provider/model pair is not in config/models.yaml
    """
    global _cached_key

    # Resolve provider and model from catalog
    from .model_catalog import resolve_selection
    
    # Use env defaults if not specified
    if provider is None:
        provider = LLM_PROVIDER
    if model is None:
        model = LLM_MODEL
    
    # Validate against catalog and get reasoning flag
    selection = resolve_selection(provider, model)
    
    # Claude Sonnet 5 only supports temperature=1
    # https://docs.anthropic.com/en/docs/about-claude/models
    if "sonnet-5" in selection.model.lower() or "claude-5" in selection.model.lower():
        if temperature != 1.0:
            logger.info(f"Adjusting temperature from {temperature} to 1.0 for {selection.model} (only supported value)")
            temperature = 1.0
    
    # Get credentials for the selected provider
    if selection.provider in ("gateway", "eng_ai"):
        base_url, api_key = _gateway_credentials()
    elif selection.provider == "openrouter":
        base_url, api_key = _openrouter_credentials()
    else:
        raise RuntimeError(
            f"Unknown provider '{selection.provider}'. "
            "Only 'gateway', 'eng_ai' and 'openrouter' are implemented."
        )
    
    # SSL configuration (applies to both providers)
    disable_ssl = os.environ.get('DISABLE_SSL_VERIFY', '').lower() in ('true', '1', 'yes')
    
    if disable_ssl:
        logger.warning(
            "⚠️  SSL verification is DISABLED (DISABLE_SSL_VERIFY=true). "
            "This is insecure and should only be used for development/testing."
        )
        import ssl
        
        _original_create_default_context = ssl.create_default_context
        
        def _unverified_context(*args, **kwargs):
            context = _original_create_default_context(*args, **kwargs)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        
        ssl.create_default_context = _unverified_context
        ssl._create_default_https_context = _unverified_context
    else:
        cert_path = os.environ.get('SSL_CERT_FILE') or os.environ.get('REQUESTS_CA_BUNDLE') or certifi.where()
        os.environ['SSL_CERT_FILE'] = cert_path
        os.environ['REQUESTS_CA_BUNDLE'] = cert_path
        logger.info(f"Using SSL certificate bundle: {cert_path}")
    
    try:
        # Build extra_body for reasoning models (OpenRouter specific)
        extra_body = {}
        if selection.reasoning and selection.provider == "openrouter":
            # OpenRouter reasoning models may support additional parameters
            # Pass through as extra_body if OpenAICompletion supports it
            extra_body = {"reasoning": {"enabled": True}}
        
        # Instantiate _NonStrictOpenAICompletion directly (not via LLM factory)
        # to pin the OpenAI transport and strip `strict` from tool schemas.
        # Both providers are OpenAI-compatible.
        llm_kwargs = {
            "model": selection.model,
            "base_url": base_url,
            "api_key": api_key,
            "temperature": temperature,
        }
        
        # Only pass extra_body if it's non-empty and the constructor accepts it
        # (OpenAICompletion may not support extra_body in all versions)
        if extra_body:
            try:
                return _NonStrictOpenAICompletion(**llm_kwargs, extra_body=extra_body)
            except TypeError:
                # Fall back without extra_body if not supported
                logger.warning(
                    f"OpenAICompletion does not support extra_body; "
                    f"reasoning parameters not passed for {selection.model}"
                )
                return _NonStrictOpenAICompletion(**llm_kwargs)
        else:
            return _NonStrictOpenAICompletion(**llm_kwargs)
            
    except AuthenticationError as e:
        # Only refetch for gateway/eng_ai (OpenRouter keys don't expire mid-process)
        if (
            refetch_on_auth_failure
            and selection.provider in ("gateway", "eng_ai")
            and _cached_key is not None
        ):
            logger.warning("Gateway authentication failed, refetching key")
            _cached_key = None
            return build_llm(provider, model, temperature, refetch_on_auth_failure=False)
        
        provider_hint = (
            "The helper may have returned an expired or invalid key."
            if selection.provider in ("gateway", "eng_ai")
            else "Check that OPENROUTER_API_KEY is correct in your .env file."
        )
        raise RuntimeError(
            f"{selection.provider.title()} authentication failed: {e}. {provider_hint}"
        ) from e
