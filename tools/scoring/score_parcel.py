"""Deterministic parcel scoring.

Pure function that takes enriched parcel data and criteria, returns
a 0-100 score plus per-dimension breakdown.
"""

from __future__ import annotations

import logging
from typing import Any

from .weights import get_cad_config, get_presentation_config, get_weights

logger = logging.getLogger(__name__)


def _cad(enrichment: dict[str, Any]) -> dict[str, Any]:
    """Return the shaped CAD parcel block, or raise so the dimension is skipped.

    Only Collin County has a CAD implementation. Everywhere else the dimension
    must drop out and let the remaining weights renormalize — scoring an absent
    fact as bad would punish a parcel for living in the wrong county.
    """
    cad = enrichment.get("cad_parcel")
    if not isinstance(cad, dict):
        raise ValueError("No cad_parcel enrichment")
    if cad.get("status") in ("error", "not_implemented"):
        raise ValueError(f"CAD lookup unavailable: {cad.get('status')}")

    parcel = cad.get("parcel")
    if not isinstance(parcel, dict):
        raise ValueError("CAD enrichment has no parcel")
    return parcel


def _cad_comps(enrichment: dict[str, Any]) -> dict[str, Any] | None:
    """Neighborhood comp cohort, when the enricher managed to fetch one."""
    cad = enrichment.get("cad_parcel")
    if not isinstance(cad, dict):
        return None
    comps = cad.get("neighborhood_comps")
    return comps if isinstance(comps, dict) else None


def _clamped_ratio_score(ratio: float, ceiling: float) -> float:
    """Map an ask-over-benchmark ratio to 0-1, where cheaper is better."""
    if ceiling <= 1.0:
        return 1.0 if ratio <= 1.0 else 0.0
    clamped = max(1.0, min(ceiling, ratio))
    return 1.0 - ((clamped - 1.0) / (ceiling - 1.0))


class DimensionScore:
    """Score breakdown for one dimension."""
    
    def __init__(
        self,
        dimension: str,
        raw_score: float,
        weight: float,
        weighted_score: float,
        explanation: str = "",
    ):
        self.dimension = dimension
        self.raw_score = raw_score  # 0-1 before weighting
        self.weight = weight
        self.weighted_score = weighted_score  # raw_score * weight
        self.explanation = explanation
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "dimension": self.dimension,
            "raw_score": self.raw_score,
            "weight": self.weight,
            "weighted_score": self.weighted_score,
            "explanation": self.explanation,
        }


class ScoreResult:
    """Scoring result with total and dimension breakdown."""
    
    def __init__(
        self,
        total_score: float,
        dimensions: list[DimensionScore],
        skipped_dimensions: list[str],
        criteria_version: str,
        highlights: list[dict[str, Any]] | None = None,
        drawbacks: list[dict[str, Any]] | None = None,
        not_assessed: list[dict[str, Any]] | None = None,
    ):
        self.total_score = total_score
        self.dimensions = dimensions
        self.skipped_dimensions = skipped_dimensions
        self.criteria_version = criteria_version
        self.highlights = highlights or []
        self.drawbacks = drawbacks or []
        self.not_assessed = not_assessed or []
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "total_score": self.total_score,
            "dimensions": {
                d.dimension: d.to_dict() for d in self.dimensions
            },
            "skipped_dimensions": self.skipped_dimensions,
            "criteria_version": self.criteria_version,
            "highlights": self.highlights,
            "drawbacks": self.drawbacks,
            "not_assessed": self.not_assessed,
        }


def _score_value_vs_comps(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score the ask against the best available value benchmark.

    Three bases in descending order of authority: the appraisal district's
    median for the parcel's own neighborhood cohort, the parcel's own appraised
    market value, and finally the LandWatch-derived county median. With none of
    them the dimension is skipped rather than scored neutral.

    Returns (0-1 score, explanation).
    """
    cad_config = get_cad_config()
    ceiling = cad_config.get("value_ratio_ceiling", 2.0)
    ask_ppa = parcel.get("basic_info", {}).get("price_per_acre")

    # 1. Neighborhood cohort median from the appraisal district.
    comps = _cad_comps(enrichment)
    if ask_ppa and comps:
        median_ppa = comps.get("median_market_per_acre")
        cohort = comps.get("count") or 0
        min_cohort = cad_config.get("min_comp_cohort", 5)
        if median_ppa and median_ppa > 0 and cohort >= min_cohort:
            ratio = ask_ppa / median_ppa
            explanation = (
                f"${ask_ppa:,.0f}/acre vs ${median_ppa:,.0f}/acre median across "
                f"{cohort} parcels in CCAD neighborhood {comps.get('nbhd_code')} "
                f"(ratio: {ratio:.2f})"
            )
            return _clamped_ratio_score(ratio, ceiling), explanation

    # 2. The parcel's own appraised market value.
    try:
        cad_parcel = _cad(enrichment)
    except ValueError:
        cad_parcel = None

    if ask_ppa and cad_parcel:
        cad_ppa = cad_parcel.get("market_per_acre")
        if cad_ppa and cad_ppa > 0:
            ratio = ask_ppa / cad_ppa
            year = cad_parcel.get("valuation_year")
            basis = cad_parcel.get("valuation_basis")
            explanation = (
                f"${ask_ppa:,.0f}/acre asked vs ${cad_ppa:,.0f}/acre CCAD "
                f"{basis} {year} market value (ratio: {ratio:.2f})"
            )
            return _clamped_ratio_score(ratio, ceiling), explanation

    # 3. LandWatch-derived county median.
    county_comps = enrichment.get("county_comps")
    if isinstance(county_comps, dict):
        comparison_ratio = county_comps.get("comparison_ratio")
        if comparison_ratio is not None:
            # This basis compares against a median of asks, where meaningfully
            # below the median is the signal, so it keeps its original 0.5-2.0
            # band rather than the 1.0-anchored appraisal band above.
            clamped = max(0.5, min(2.0, comparison_ratio))
            raw_score = 1.0 - ((clamped - 0.5) / 1.5)
            median_ppa = county_comps.get("county_median_ppa", 0)
            explanation = (
                f"${ask_ppa or 0:,.0f}/acre vs county median ${median_ppa:,.0f}/acre "
                f"(ratio: {comparison_ratio:.2f})"
            )
            return raw_score, explanation

    raise ValueError("No comparable value basis available")


def _score_acreage_fit(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score how well acreage matches criteria range.
    
    Returns (0-1 score, explanation).
    """
    # The appraisal roll is a better acreage source than a listing headline,
    # so prefer it and note where the figure came from.
    acres = None
    source = "listing"
    try:
        cad_parcel = _cad(enrichment)
    except ValueError:
        cad_parcel = None

    if cad_parcel:
        acres = (cad_parcel.get("land") or {}).get("landSizeAcres")
        if acres:
            source = "CCAD"

    if acres is None:
        acres = parcel.get("basic_info", {}).get("acres")
    if acres is None:
        raise ValueError("Missing basic_info.acres")
    
    # Handle None values explicitly (criteria may have null for min/max)
    acres_min = criteria.get("acres_min")
    if acres_min is None:
        acres_min = 0
    
    acres_max = criteria.get("acres_max")
    if acres_max is None:
        acres_max = float("inf")
    
    # Perfect score if within range
    if acres_min <= acres <= acres_max:
        raw_score = 1.0
        explanation = f"{acres:.1f} acres ({source}, within target {acres_min}-{acres_max})"
    else:
        # Penalize distance from nearest bound
        if acres < acres_min:
            distance = acres_min - acres
            penalty = min(1.0, distance / acres_min)
            raw_score = 1.0 - (penalty * 0.5)
            explanation = f"{acres:.1f} acres ({source}, below min {acres_min})"
        else:
            distance = acres - acres_max
            penalty = min(1.0, distance / acres_max)
            raw_score = 1.0 - (penalty * 0.5)
            explanation = f"{acres:.1f} acres ({source}, above max {acres_max})"
    
    # Appraised and GIS acreage disagreeing means one of them is stale, which
    # weakens every acreage judgement made above.
    if cad_parcel:
        cad_config = get_cad_config()
        variance = cad_parcel.get("acreage_variance")
        tolerance = cad_config.get("acreage_variance_tolerance", 0.05)
        if variance is not None and variance > tolerance:
            raw_score *= 1.0 - cad_config.get("acreage_variance_penalty", 0.25)
            explanation += (
                f"; GIS acreage differs from appraised by {variance:.0%}"
            )
    
    return raw_score, explanation


def _score_criteria_match(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score how well parcel matches stated criteria.
    
    Returns (0-1 score, explanation).
    """
    # Check price range
    price = parcel.get("basic_info", {}).get("price")
    if price is None:
        raise ValueError("Missing basic_info.price")
    
    # Handle None values explicitly (criteria may have null for min/max)
    price_min = criteria.get("price_min")
    if price_min is None:
        price_min = 0
    
    price_max = criteria.get("price_max")
    if price_max is None:
        price_max = float("inf")
    
    price_match = 1.0 if price_min <= price <= price_max else 0.7
    
    # Check property types if specified
    requested_types = set(criteria.get("property_types") or [])
    parcel_types = set(parcel.get("basic_info", {}).get("property_types") or [])
    
    if requested_types:
        type_overlap = len(requested_types & parcel_types)
        type_match = type_overlap / len(requested_types) if requested_types else 1.0
    else:
        type_match = 1.0
    
    sub_scores = [price_match, type_match]
    explanation = f"${price:,.0f} (target: ${price_min:,.0f}-${price_max:,.0f})"
    if requested_types and parcel_types:
        matches = requested_types & parcel_types
        explanation += f", types: {', '.join(matches) if matches else 'none match'}"

    # Jurisdiction, from the CAD taxing-entity code rather than the mailing
    # city. A McKinney mailing address on unincorporated land answers to the
    # county, not the city, and that decides who writes the zoning rules.
    try:
        cad_parcel = _cad(enrichment)
    except ValueError:
        cad_parcel = None

    if cad_parcel:
        jurisdiction = cad_parcel.get("city")
        requested_city = criteria.get("city")
        if jurisdiction and requested_city:
            city_match = 1.0 if requested_city.strip().lower() in jurisdiction.lower() else 0.5
            sub_scores.append(city_match)
            explanation += f", jurisdiction: {jurisdiction}"
        elif jurisdiction:
            explanation += f", jurisdiction: {jurisdiction}"

    raw_score = sum(sub_scores) / len(sub_scores)
    
    return raw_score, explanation


def _score_water_and_terrain(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score based on water features and terrain from description.
    
    Returns (0-1 score, explanation).
    """
    detail = enrichment.get("landwatch_detail", {})
    description = detail.get("description", "").lower()
    
    # Look for water and terrain keywords
    water_keywords = ["creek", "river", "pond", "lake", "water", "stream"]
    terrain_keywords = ["views", "hill", "mountain", "valley", "flat", "rolling"]
    
    water_count = sum(1 for kw in water_keywords if kw in description)
    terrain_count = sum(1 for kw in terrain_keywords if kw in description)
    
    # Normalize to 0-1
    water_score = min(1.0, water_count / 2.0)
    terrain_score = min(1.0, terrain_count / 2.0)
    raw_score = (water_score + terrain_score) / 2.0
    
    features = []
    if water_count > 0:
        features.append(f"{water_count} water mention(s)")
    if terrain_count > 0:
        features.append(f"{terrain_count} terrain mention(s)")
    
    explanation = ", ".join(features) if features else "no notable features"
    
    return raw_score, explanation


def _score_access_and_utilities(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score based on access and utilities from description.
    
    Returns (0-1 score, explanation).
    """
    detail = enrichment.get("landwatch_detail", {})
    description = detail.get("description", "").lower()
    
    # Look for access and utility keywords
    access_keywords = ["road", "paved", "highway", "access", "frontage", "county road"]
    utility_keywords = ["electric", "electricity", "power", "water well", "septic", "utilities"]
    
    access_count = sum(1 for kw in access_keywords if kw in description)
    utility_count = sum(1 for kw in utility_keywords if kw in description)
    
    # Normalize to 0-1
    access_score = min(1.0, access_count / 2.0)
    utility_score = min(1.0, utility_count / 2.0)
    raw_score = (access_score + utility_score) / 2.0
    
    features = []
    if access_count > 0:
        features.append(f"{access_count} access mention(s)")
    if utility_count > 0:
        features.append(f"{utility_count} utility mention(s)")
    
    explanation = ", ".join(features) if features else "no mentions"
    
    return raw_score, explanation


def _score_market_signal(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score based on market signals (price cuts, days on market).
    
    Returns (0-1 score, explanation).
    """
    detail = enrichment.get("landwatch_detail", {})
    days_on_market = detail.get("days_on_market")
    price_history = detail.get("price_history", [])
    
    # Score days on market: longer = better negotiating position
    if days_on_market is not None:
        # 0-30 days = 0.5, 90+ days = 1.0
        dom_score = min(1.0, 0.5 + (days_on_market / 180.0))
    else:
        dom_score = 0.5
    
    # Score price cuts: any cut = positive signal
    if len(price_history) > 1:
        prices = [h["price"] for h in price_history]
        has_cut = any(prices[i] > prices[i+1] for i in range(len(prices)-1))
        cut_score = 1.0 if has_cut else 0.7
    else:
        cut_score = 0.7
    
    sub_scores = [dom_score, cut_score]
    explanation = f"{days_on_market or 'unknown'} days on market"
    if len(price_history) > 1:
        explanation += f", {len(price_history)} price changes"

    # Ownership history is the other half of seller motivation: a long-held
    # tract has basis to spare, while an owner-occupied homestead is a slower
    # and pricier sale than an absentee holding.
    try:
        cad_parcel = _cad(enrichment)
    except ValueError:
        cad_parcel = None

    if cad_parcel:
        cad_config = get_cad_config()
        held_years = cad_parcel.get("held_years")
        if held_years is not None:
            target = cad_config.get("held_years_target", 15.0)
            tenure_score = min(1.0, held_years / target) if target > 0 else 1.0
            sub_scores.append(tenure_score)
            explanation += f", held {held_years:.0f} years"

        if cad_parcel.get("owner_occupied"):
            occupancy_score = 1.0 - cad_config.get("owner_occupied_penalty", 0.2)
            sub_scores.append(occupancy_score)
            explanation += ", owner-occupied"
        elif cad_parcel.get("owner_occupied") is False:
            sub_scores.append(1.0)
            explanation += ", absentee owner"

    raw_score = sum(sub_scores) / len(sub_scores)
    
    return raw_score, explanation


def _score_tax_burden(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score the annual carrying cost implied by the parcel's taxing entities.

    Every entity on the roll is a separate levy. Special districts (MUD, TIF,
    SBCL) matter most because they are the ones a buyer does not see in a
    listing. An ag valuation cuts the bill today but defers a rollback.

    Returns (0-1 score, explanation).
    """
    cad_parcel = _cad(enrichment)
    cad_config = get_cad_config()
    entity = cad_parcel.get("entity") or {}

    raw_score = 1.0
    notes: list[str] = []

    codes_raw = entity.get("entityCodes") or ""
    codes = [c.strip() for c in codes_raw.split(",") if c.strip()]
    baseline = cad_config.get("baseline_entity_count", 3)
    extra = max(0, len(codes) - baseline)
    if extra:
        raw_score -= extra * cad_config.get("entity_penalty", 0.10)
    notes.append(f"{len(codes)} taxing entities")

    for flag, key, label in (
        ("entityMUD", "mud_penalty", "MUD"),
        ("entityTIF", "tif_penalty", "TIF"),
        ("entitySBCL", "sbcl_penalty", "special district"),
    ):
        if entity.get(flag) == "T":
            raw_score -= cad_config.get(key, 0.1)
            notes.append(f"in a {label}")

    if cad_parcel.get("ag_exempt"):
        raw_score += cad_config.get("ag_valuation_credit", 0.25)
        ag_loss_ratio = cad_parcel.get("ag_loss_ratio")
        if ag_loss_ratio:
            raw_score -= ag_loss_ratio * cad_config.get("ag_rollback_penalty", 0.30)
            notes.append(
                f"ag valuation hides {ag_loss_ratio:.0%} of market value "
                "(rollback on change of use)"
            )
        else:
            notes.append("ag valuation")

    raw_score = max(0.0, min(1.0, raw_score))
    return raw_score, ", ".join(notes)


def _score_land_use_fit(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score the appraised land use against what the buyer actually wants.

    The appraisal district's own land classification is a firmer statement of
    what a parcel is than a listing's property_types. Existing improvements
    cut both ways: a liability to a raw-land buyer, an asset to a house buyer.

    Returns (0-1 score, explanation).
    """
    cad_parcel = _cad(enrichment)
    cad_config = get_cad_config()
    land = cad_parcel.get("land") or {}
    status = cad_parcel.get("status") or {}

    land_type = land.get("landTypeCode")
    categories_raw = land.get("landCategoryCodes") or ""
    categories = [c.strip() for c in categories_raw.split(",") if c.strip()]
    raw_prefixes = cad_config.get("raw_land_category_codes", ["D1", "D2"])

    if not land_type and not categories:
        raise ValueError("No CAD land classification")

    is_raw_land = any(
        c.startswith(tuple(raw_prefixes)) for c in categories
    ) or (land_type or "").startswith(tuple(raw_prefixes))
    
    # What the buyer asked for. Absent an explicit signal, treat the search as
    # raw-land intent — that is what this product is for.
    requested = {t.lower() for t in (criteria.get("property_types") or [])}
    wants_house = bool(requested & {"house", "home", "residential", "farms", "homesite"})

    raw_score = 1.0 if is_raw_land else 0.6
    notes = [f"appraised as {land_type or ', '.join(categories)}"]

    if cad_parcel.get("improved"):
        improvement = cad_parcel.get("improvement") or {}
        year_built = improvement.get("imprvYearBuilt")
        if wants_house:
            notes.append(f"improved{f' ({year_built})' if year_built else ''}")
        else:
            raw_score *= 1.0 - cad_config.get("improved_penalty_raw_land", 0.50)
            notes.append(
                f"carries improvements{f' built {year_built}' if year_built else ''} "
                "not asked for"
            )

    sub_type = status.get("propSubType")
    if sub_type:
        notes.append(f"CCAD subtype {sub_type}")

    return max(0.0, min(1.0, raw_score)), ", ".join(notes)


def _score_developability(
    parcel: dict[str, Any], criteria: dict[str, Any], enrichment: dict[str, Any]
) -> tuple[float, str]:
    """Score how workable the parcel is as a physical and legal object.

    Acreage says nothing about shape. A long thin strip and a square tract of
    equal size are not equally usable, and a fractional undivided interest is
    not a purchase at all.

    Returns (0-1 score, explanation).
    """
    cad_parcel = _cad(enrichment)
    cad_config = get_cad_config()
    status = cad_parcel.get("status") or {}

    # Undivided interest means you would be buying a share alongside unknown
    # co-owners. That is a disqualifier, not a discount.
    if status.get("udiPropFlag") == "T":
        return 0.0, "fractional undivided interest (UDI) — not a clean fee-simple buy"

    notes: list[str] = []
    compactness = cad_parcel.get("compactness")
    if compactness is None:
        raise ValueError("No parcel geometry for developability")

    floor = cad_config.get("compactness_floor", 0.20)
    target = cad_config.get("compactness_target", 0.60)
    if target <= floor:
        shape_score = 1.0
    else:
        shape_score = (compactness - floor) / (target - floor)
    raw_score = max(0.0, min(1.0, shape_score))
    notes.append(f"shape compactness {compactness:.2f}")

    if status.get("propSplitFromPID"):
        raw_score += cad_config.get("split_precedent_credit", 0.15)
        notes.append("split from a parent parcel (subdivision precedent)")

    if status.get("protestCode"):
        raw_score -= cad_config.get("protest_penalty", 0.10)
        notes.append("valuation under protest")

    return max(0.0, min(1.0, raw_score)), ", ".join(notes)


# Dimension scoring functions
DIMENSION_SCORERS = {
    "value_vs_comps": _score_value_vs_comps,
    "acreage_fit": _score_acreage_fit,
    "criteria_match": _score_criteria_match,
    "land_use_fit": _score_land_use_fit,
    "developability": _score_developability,
    "tax_burden": _score_tax_burden,
    "water_and_terrain": _score_water_and_terrain,
    "access_and_utilities": _score_access_and_utilities,
    "market_signal": _score_market_signal,
}


# User-facing labels for each dimension
DIMENSION_LABELS = {
    "value_vs_comps": "Value vs comparables",
    "acreage_fit": "Acreage fit",
    "criteria_match": "Criteria match",
    "land_use_fit": "Land use fit",
    "developability": "Developability",
    "tax_burden": "Tax burden",
    "water_and_terrain": "Water and terrain",
    "access_and_utilities": "Access and utilities",
    "market_signal": "Market signal",
}


def score_parcel(
    parcel: dict[str, Any],
    criteria: dict[str, Any],
    enrichment: dict[str, Any],
) -> ScoreResult:
    """Score an enriched parcel deterministically.
    
    Args:
        parcel: Basic parcel data (location, basic_info)
        criteria: Search/investment criteria
        enrichment: Enrichment data from all sources
        
    Returns:
        ScoreResult with total score (0-100) and dimension breakdown
        
    Raises:
        ValueError: If required data is missing
    """
    from .weights import get_version, get_weights
    
    weights = get_weights()
    dimensions: list[DimensionScore] = []
    skipped: list[str] = []
    skipped_reasons: dict[str, str] = {}
    
    # Score each dimension
    for dim_name, weight in weights.items():
        scorer = DIMENSION_SCORERS.get(dim_name)
        if not scorer:
            reason = "No scorer implemented"
            logger.warning(f"No scorer for dimension '{dim_name}', skipping")
            skipped.append(dim_name)
            skipped_reasons[dim_name] = reason
            continue
        
        try:
            raw_score, explanation = scorer(parcel, criteria, enrichment)
            weighted = raw_score * weight
            dimensions.append(
                DimensionScore(dim_name, raw_score, weight, weighted, explanation)
            )
        except (ValueError, KeyError) as e:
            reason = str(e)
            logger.warning(f"Cannot score dimension '{dim_name}': {e}")
            skipped.append(dim_name)
            skipped_reasons[dim_name] = reason
    
    # If we skipped dimensions, renormalize weights
    if skipped:
        logger.info(f"Skipped dimensions: {skipped}")
        active_weight = sum(d.weight for d in dimensions)
        if active_weight > 0:
            for dim in dimensions:
                dim.weighted_score = (dim.weighted_score / active_weight)
    
    # Calculate total (scale to 0-100)
    total = sum(d.weighted_score for d in dimensions) * 100.0
    
    # Derive highlights, drawbacks, and not_assessed
    pres_config = get_presentation_config()
    highlight_threshold = pres_config.get("highlight_threshold", 0.75)
    drawback_threshold = pres_config.get("drawback_threshold", 0.35)
    max_highlights = pres_config.get("max_highlights", 5)
    max_drawbacks = pres_config.get("max_drawbacks", 5)
    
    # Build highlights and drawbacks with impact score for ranking
    highlight_candidates: list[tuple[float, dict[str, Any]]] = []
    drawback_candidates: list[tuple[float, dict[str, Any]]] = []
    
    for dim in dimensions:
        label = DIMENSION_LABELS.get(dim.dimension, dim.dimension)
        item = {
            "dimension": dim.dimension,
            "label": label,
            "raw_score": dim.raw_score,
            "weight": dim.weight,
            "detail": dim.explanation,
        }
        
        # Calculate impact: weight * deviation from neutral 0.5
        impact = dim.weight * abs(dim.raw_score - 0.5)
        
        if dim.raw_score >= highlight_threshold:
            highlight_candidates.append((impact, item))
        elif dim.raw_score <= drawback_threshold:
            drawback_candidates.append((impact, item))
    
    # Sort by impact descending
    highlight_candidates.sort(key=lambda x: x[0], reverse=True)
    drawback_candidates.sort(key=lambda x: x[0], reverse=True)
    
    # Pin hard zeros (disqualifiers) to the top of drawbacks
    hard_zeros = [(impact, item) for impact, item in drawback_candidates if item["raw_score"] == 0.0]
    non_zeros = [(impact, item) for impact, item in drawback_candidates if item["raw_score"] != 0.0]
    drawback_candidates = hard_zeros + non_zeros
    
    # Extract items and apply caps
    highlights = [item for _, item in highlight_candidates[:max_highlights]]
    drawbacks = [item for _, item in drawback_candidates[:max_drawbacks]]
    
    # Build not_assessed list
    not_assessed = [
        {
            "dimension": dim_name,
            "label": DIMENSION_LABELS.get(dim_name, dim_name),
            "reason": skipped_reasons.get(dim_name, "Unknown"),
        }
        for dim_name in skipped
    ]
    
    return ScoreResult(
        total_score=total,
        dimensions=dimensions,
        skipped_dimensions=skipped,
        criteria_version=get_version(),
        highlights=highlights,
        drawbacks=drawbacks,
        not_assessed=not_assessed,
    )
