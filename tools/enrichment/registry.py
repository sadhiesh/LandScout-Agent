"""Enrichment registry for pluggable data sources.

Each enricher is a typed function that takes a parcel and returns additional
facts to merge onto parcel.enrichment. Enrichers are discovered through the
registry so the Enricher agent never hardcodes a source list.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


class EnricherProtocol(Protocol):
    """Protocol for enrichment sources."""
    
    name: str
    enabled: bool
    
    def enrich(self, parcel: dict[str, Any]) -> dict[str, Any]:
        """Enrich a parcel with additional facts.
        
        Args:
            parcel: Parcel data including property_id, location, basic_info
            
        Returns:
            Dict of enrichment facts to merge onto parcel.enrichment
            
        Raises:
            Exception: On failure (caught and logged by registry)
        """
        ...


class Enricher:
    """Enricher wrapper with metadata."""
    
    def __init__(
        self,
        name: str,
        func: Callable[[dict[str, Any]], dict[str, Any]],
        enabled: bool = True,
    ):
        self.name = name
        self.func = func
        self.enabled = enabled
    
    def enrich(self, parcel: dict[str, Any]) -> dict[str, Any]:
        """Execute the enrichment function."""
        return self.func(parcel)


# Global enricher registry
REGISTRY: list[Enricher] = []


def register(
    name: str, enabled: bool = True
) -> Callable[[Callable], Callable]:
    """Decorator to register an enricher.
    
    Usage:
        @register("landwatch_detail")
        def enrich_landwatch_detail(parcel: dict) -> dict:
            ...
    """
    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable:
        REGISTRY.append(Enricher(name, func, enabled))
        logger.info(
            f"Registered enricher '{name}' ({'enabled' if enabled else 'disabled'})"
        )
        return func
    
    return decorator


def get_enabled_enrichers() -> list[Enricher]:
    """Get all enabled enrichers from the registry."""
    return [e for e in REGISTRY if e.enabled]


def run_enrichment(
    parcel: dict[str, Any],
    enrichers: list[Enricher] | None = None,
    progress_callback: Callable[[str, str, dict[str, Any] | None], None] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Run all enabled enrichers on a parcel.
    
    Args:
        parcel: Parcel data to enrich
        enrichers: Optional list of enrichers (defaults to all enabled)
        progress_callback: Optional callback(kind, summary, data) for trace events
        
    Returns:
        Tuple of (enriched_data, sources_used, sources_failed)
    """
    if enrichers is None:
        enrichers = get_enabled_enrichers()
    
    enriched_data: dict[str, Any] = {}
    sources_used: list[str] = []
    sources_failed: list[str] = []
    
    # Build a working parcel that accumulates enrichments as we go
    working_parcel = parcel.copy()
    working_parcel["enrichment"] = {}
    
    for enricher in enrichers:
        try:
            logger.info(f"Running enricher: {enricher.name}")
            
            # Emit tool_call event if callback provided
            if progress_callback:
                progress_callback(
                    "tool_call",
                    f"🛠 {enricher.name}",
                    {"tool": enricher.name, "parcel_id": parcel.get("property_id")}
                )
            
            import time
            start_time = time.time()
            # Pass the working parcel with accumulated enrichments
            result = enricher.enrich(working_parcel)
            duration_ms = (time.time() - start_time) * 1000
            
            enriched_data[enricher.name] = result
            # Also add to working parcel so next enrichers can access it
            working_parcel["enrichment"][enricher.name] = result
            sources_used.append(enricher.name)
            logger.info(f"Enricher '{enricher.name}' succeeded")
            
            # Emit tool_result event if callback provided
            if progress_callback:
                # Determine summary based on result status
                status = result.get("status") if isinstance(result, dict) else "success"
                summary = f"✓ {enricher.name}"
                if status == "not_implemented":
                    summary = f"⊘ {enricher.name} (not implemented)"
                elif status == "error":
                    summary = f"✗ {enricher.name} (error)"
                
                progress_callback(
                    "tool_result",
                    summary,
                    {
                        "tool": enricher.name,
                        "duration_ms": duration_ms,
                        "status": status,
                    }
                )
                
        except Exception as e:
            logger.error(
                f"Enricher '{enricher.name}' failed: {type(e).__name__}: {e}"
            )
            sources_failed.append(enricher.name)
            enriched_data[enricher.name] = None
            
            # Emit error event if callback provided
            if progress_callback:
                progress_callback(
                    "error",
                    f"✗ {enricher.name} failed: {type(e).__name__}",
                    {"tool": enricher.name, "error": str(e)}
                )
    
    return enriched_data, sources_used, sources_failed
