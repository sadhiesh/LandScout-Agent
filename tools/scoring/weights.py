"""Scoring weights loader from config/criteria.yaml.

All scoring weights live in one place so they can be tuned without code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Path to criteria configuration
CRITERIA_PATH = Path(__file__).parent.parent.parent / "config" / "criteria.yaml"


def load_criteria() -> dict[str, Any]:
    """Load criteria configuration from YAML.
    
    Returns:
        Dict with version, defaults, weights, and shortlist_size
        
    Raises:
        FileNotFoundError: If criteria.yaml doesn't exist
        yaml.YAMLError: If criteria.yaml is malformed
    """
    with CRITERIA_PATH.open() as f:
        return yaml.safe_load(f)


def get_weights() -> dict[str, float]:
    """Get scoring dimension weights.
    
    Returns:
        Dict mapping dimension name to weight (0-1, should sum to 1.0)
    """
    criteria = load_criteria()
    return criteria.get("weights", {})


def get_version() -> str:
    """Get criteria version identifier.
    
    Used to track which weights produced a given score.
    """
    criteria = load_criteria()
    return criteria.get("version", "unknown")


def get_defaults() -> dict[str, Any]:
    """Get default search criteria.
    
    These are overridden by user input but provide sensible starting values.
    """
    criteria = load_criteria()
    return criteria.get("defaults", {})


def get_shortlist_size() -> int:
    """Get target shortlist size.
    
    Number of top-ranked parcels to return to the user.
    """
    criteria = load_criteria()
    return criteria.get("shortlist_size", 10)


def get_cad_config() -> dict[str, Any]:
    """Get tunables for the dimensions that read county appraisal data.

    Returned as a plain dict so a scorer can read a key with a local default
    and a missing entry never crashes a run mid-shortlist.
    """
    criteria = load_criteria()
    return criteria.get("cad", {})


def get_presentation_config() -> dict[str, Any]:
    """Get presentation thresholds for highlights/drawbacks derivation.

    Returned as a plain dict with defaults so a missing config never crashes.
    """
    criteria = load_criteria()
    return criteria.get("presentation", {})


def get_gate_config() -> dict[str, Any]:
    """Get criteria sufficiency gate configuration.
    
    Controls when the Supervisor asks a clarifying question instead of
    searching. Defaults here keep the gate inert if the block is absent,
    so a missing config never blocks a search.
    """
    criteria = load_criteria()
    gate = criteria.get("criteria_gate", {})
    
    return {
        "max_rounds": gate.get("max_rounds", 2),
        "min_signals": gate.get("min_signals", 1),
        "confirm_inferred_location": gate.get("confirm_inferred_location", True),
        "offer_relax_on_zero": gate.get("offer_relax_on_zero", True),
        "search_required": gate.get("search_required", ["state"]),
    }


def validate_weights(weights: dict[str, float]) -> None:
    """Validate that weights are sensible.
    
    Args:
        weights: Weight dict to validate
        
    Raises:
        ValueError: If weights don't sum to ~1.0 or have negative values
    """
    if not weights:
        raise ValueError("No weights defined in criteria.yaml")
    
    total = sum(weights.values())
    if not (0.99 <= total <= 1.01):
        raise ValueError(
            f"Weights sum to {total:.3f}, expected ~1.0. "
            f"Check config/criteria.yaml"
        )
    
    for dim, weight in weights.items():
        if weight < 0:
            raise ValueError(f"Negative weight for dimension '{dim}': {weight}")


# Validate on import
validate_weights(get_weights())
