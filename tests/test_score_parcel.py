"""Tests for deterministic parcel scoring against CAD enrichment."""

from __future__ import annotations

import pytest

from tools.scoring.score_parcel import (
    DIMENSION_SCORERS,
    _score_developability,
    _score_land_use_fit,
    _score_tax_burden,
    _score_value_vs_comps,
    score_parcel,
)
from tools.scoring.weights import get_weights


CRITERIA = {"acres_min": 10, "acres_max": 20, "price_min": 0, "price_max": 2_000_000}


def make_parcel(price_per_acre: float = 100_000.0) -> dict:
    return {
        "property_id": 1,
        "location": {"county": "Collin County", "city": "Mckinney", "state": "TX"},
        "basic_info": {
            "acres": 15.538,
            "price": 1_500_000,
            "price_per_acre": price_per_acre,
            "property_types": ["Undeveloped Land"],
        },
    }


def make_cad_parcel(**overrides) -> dict:
    """A shaped CCAD record, matching what _shape_parcel produces."""
    parcel = {
        "parcel_id": "R-6741-004-0570-1",
        "property_id": 2121800,
        "city": "Unincorporated (Collin County)",
        "gis_acres": 15.055,
        "valuation": {"market": 1_296_978, "land": 823_514, "ag_loss": 769_002},
        "valuation_year": 2026,
        "valuation_basis": "previous",
        "market_per_acre": 83_471.0,
        "land_per_acre": 53_000.0,
        "ag_exempt": True,
        "ag_loss_ratio": 0.593,
        "improved": True,
        "acreage_variance": 0.031,
        "compactness": 0.229,
        "owner_occupied": True,
        "held_years": 16.0,
        "land": {
            "landSizeAcres": 15.538,
            "landAgAcres": 14.538,
            "landTypeCode": "D1IP",
            "landCategoryCodes": "D1,E",
        },
        "improvement": {"imprvMainArea": 2506, "imprvYearBuilt": 1999},
        "entity": {
            "entityCodes": "GCN,JCN,SMC,ECC1",
            "entitySchoolCode": "SMC",
            "entityCityCode": None,
            "entityMUD": "F",
            "entityTIF": "F",
            "entitySBCL": "F",
        },
        "status": {
            "nbhdCode": "SMCR",
            "propSubType": "Residential",
            "exemptCodes": "HS",
            "exemptHmstdFlag": "T",
            "protestCode": None,
            "udiPropFlag": "F",
            "propSplitFromPID": None,
        },
    }
    parcel.update(overrides)
    return parcel


def make_enrichment(cad_parcel: dict | None = None, neighborhood_comps: dict | None = None, **extra) -> dict:
    enrichment = dict(extra)
    if cad_parcel is not None:
        block = {"parcel": cad_parcel, "matches": [], "warnings": []}
        if neighborhood_comps is not None:
            block["neighborhood_comps"] = neighborhood_comps
        enrichment["cad_parcel"] = block
    return enrichment


class TestValueVsCompsCascade:
    """Neighborhood median, then the parcel's own appraisal, then county comps."""

    def test_prefers_neighborhood_median(self):
        comps = {
            "nbhd_code": "SMCR",
            "count": 34,
            "median_market_per_acre": 100_000.0,
            "median_land_per_acre": 60_000.0,
        }
        enrichment = make_enrichment(
            make_cad_parcel(),
            comps,
            county_comps={"comparison_ratio": 0.5, "county_median_ppa": 200_000},
        )

        score, explanation = _score_value_vs_comps(make_parcel(100_000.0), CRITERIA, enrichment)

        assert "neighborhood SMCR" in explanation
        assert score == pytest.approx(1.0)

    def test_thin_cohort_falls_through_to_own_appraisal(self):
        comps = {"nbhd_code": "SMCR", "count": 2, "median_market_per_acre": 100_000.0}
        enrichment = make_enrichment(make_cad_parcel(), comps)

        score, explanation = _score_value_vs_comps(make_parcel(83_471.0), CRITERIA, enrichment)

        assert "CCAD previous 2026 market value" in explanation
        assert score == pytest.approx(1.0)

    def test_falls_back_to_county_comps_without_cad(self):
        enrichment = make_enrichment(
            None, county_comps={"comparison_ratio": 0.5, "county_median_ppa": 200_000}
        )

        score, explanation = _score_value_vs_comps(make_parcel(), CRITERIA, enrichment)

        assert "county median" in explanation
        assert score == pytest.approx(1.0)

    def test_skips_rather_than_scoring_neutral(self):
        """A dead data source must not masquerade as an average parcel."""
        with pytest.raises(ValueError, match="No comparable value basis"):
            _score_value_vs_comps(make_parcel(), CRITERIA, make_enrichment(None))

    def test_asking_double_the_appraisal_scores_zero(self):
        enrichment = make_enrichment(make_cad_parcel())

        score, _ = _score_value_vs_comps(make_parcel(166_942.0), CRITERIA, enrichment)

        assert score == pytest.approx(0.0)


class TestDevelopability:
    def test_udi_is_a_hard_disqualifier(self):
        cad = make_cad_parcel(status={"udiPropFlag": "T", "nbhdCode": "SMCR"})

        score, explanation = _score_developability(make_parcel(), CRITERIA, make_enrichment(cad))

        assert score == 0.0
        assert "undivided interest" in explanation

    def test_compact_tract_outscores_irregular_one(self):
        irregular = make_cad_parcel(compactness=0.229)
        compact = make_cad_parcel(compactness=0.70)

        low, _ = _score_developability(make_parcel(), CRITERIA, make_enrichment(irregular))
        high, _ = _score_developability(make_parcel(), CRITERIA, make_enrichment(compact))

        assert low < high
        assert high == pytest.approx(1.0)

    def test_split_precedent_credits_and_protest_penalises(self):
        base = make_cad_parcel(compactness=0.40)
        split = make_cad_parcel(
            compactness=0.40,
            status={"udiPropFlag": "F", "propSplitFromPID": 999, "protestCode": None},
        )

        plain, _ = _score_developability(make_parcel(), CRITERIA, make_enrichment(base))
        with_split, explanation = _score_developability(
            make_parcel(), CRITERIA, make_enrichment(split)
        )

        assert with_split > plain
        assert "subdivision precedent" in explanation

    def test_missing_geometry_skips(self):
        cad = make_cad_parcel(compactness=None)

        with pytest.raises(ValueError, match="No parcel geometry"):
            _score_developability(make_parcel(), CRITERIA, make_enrichment(cad))


class TestTaxBurden:
    def test_ag_valuation_credits_but_rollback_bites(self):
        score, explanation = _score_tax_burden(
            make_parcel(), CRITERIA, make_enrichment(make_cad_parcel())
        )

        assert 0.0 < score <= 1.0
        assert "4 taxing entities" in explanation
        assert "rollback" in explanation

    def test_special_districts_reduce_the_score(self):
        plain = make_cad_parcel()
        in_mud = make_cad_parcel(
            entity=dict(plain["entity"], entityMUD="T", entityTIF="T")
        )

        base, _ = _score_tax_burden(make_parcel(), CRITERIA, make_enrichment(plain))
        burdened, explanation = _score_tax_burden(
            make_parcel(), CRITERIA, make_enrichment(in_mud)
        )

        assert burdened < base
        assert "in a MUD" in explanation

    def test_skips_outside_collin_county(self):
        enrichment = {"cad_parcel": {"status": "not_implemented", "county": "Grayson"}}

        with pytest.raises(ValueError, match="CAD lookup unavailable"):
            _score_tax_burden(make_parcel(), CRITERIA, enrichment)


class TestLandUseFit:
    def test_raw_land_scores_above_developed(self):
        raw = make_cad_parcel(improved=False)
        developed = make_cad_parcel(
            improved=False,
            land={"landTypeCode": "A1", "landCategoryCodes": "A1", "landSizeAcres": 15.5},
        )

        raw_score, _ = _score_land_use_fit(make_parcel(), CRITERIA, make_enrichment(raw))
        dev_score, _ = _score_land_use_fit(make_parcel(), CRITERIA, make_enrichment(developed))

        assert raw_score > dev_score

    def test_unwanted_improvements_penalise_a_raw_land_buyer(self):
        enrichment = make_enrichment(make_cad_parcel(improved=True))

        score, explanation = _score_land_use_fit(make_parcel(), CRITERIA, enrichment)

        assert score < 1.0
        assert "not asked for" in explanation

    def test_improvements_are_fine_for_a_house_buyer(self):
        criteria = dict(CRITERIA, property_types=["House"])
        enrichment = make_enrichment(make_cad_parcel(improved=True))

        score, explanation = _score_land_use_fit(make_parcel(), criteria, enrichment)

        assert score == pytest.approx(1.0)
        assert "not asked for" not in explanation

    def test_missing_classification_skips(self):
        cad = make_cad_parcel(land={"landSizeAcres": 15.5})

        with pytest.raises(ValueError, match="No CAD land classification"):
            _score_land_use_fit(make_parcel(), CRITERIA, make_enrichment(cad))


class TestScoreParcel:
    def test_every_weighted_dimension_has_a_scorer(self):
        assert set(get_weights()) <= set(DIMENSION_SCORERS)

    def test_full_cad_run_scores_all_dimensions(self):
        enrichment = make_enrichment(
            make_cad_parcel(),
            {"nbhd_code": "SMCR", "count": 34, "median_market_per_acre": 100_000.0},
            landwatch_detail={
                "description": "Rolling pasture with a creek, county road frontage, electric at the road",
                "days_on_market": 90,
                "price_history": [{"price": 1_600_000}, {"price": 1_500_000}],
            },
        )

        result = score_parcel(make_parcel(), CRITERIA, enrichment)

        assert result.skipped_dimensions == []
        assert 0.0 < result.total_score <= 100.0
        assert result.criteria_version == "2026-09-03"

    def test_renormalizes_when_cad_is_absent(self):
        """Without CAD the run still scores 0-100 on the surviving dimensions."""
        enrichment = {
            "landwatch_detail": {
                "description": "Creek frontage, paved road access, electricity available",
                "days_on_market": 45,
                "price_history": [],
            }
        }

        result = score_parcel(make_parcel(), CRITERIA, enrichment)

        assert set(result.skipped_dimensions) == {
            "value_vs_comps",
            "land_use_fit",
            "developability",
            "tax_burden",
        }
        assert 0.0 < result.total_score <= 100.0

    def test_a_skipped_dimension_is_not_scored_as_zero(self):
        """Dropping a dimension must not drag the total down."""
        detail = {
            "landwatch_detail": {
                "description": "creek pond river rolling hills views paved road frontage electricity septic",
                "days_on_market": 200,
                "price_history": [{"price": 2_000_000}, {"price": 1_500_000}],
            }
        }

        without_cad = score_parcel(make_parcel(), CRITERIA, dict(detail))

        # All surviving dimensions score near their maximum, so the total must
        # too — a zero-filled skip would leave it far below 100.
        assert without_cad.total_score > 80.0


class TestHighlightsAndDrawbacks:
    """Presentation fields derived from dimension scores."""

    def test_highlights_above_threshold(self):
        """Dimensions scoring >= highlight_threshold appear in highlights."""
        # Asking $10k/acre vs $50k/acre median = strong value = highlight
        enrichment = make_enrichment(
            cad_parcel=make_cad_parcel(parcel_id="TEST", ag_exempt=True),
            neighborhood_comps={"nbhd_code": "TEST", "count": 10, "median_market_per_acre": 50_000.0},
            landwatch_detail={"description": "creek river pond views rolling hills paved road electric water", "days_on_market": 120, "price_history": []},
        )

        parcel = make_parcel()
        parcel["basic_info"]["price"] = 500_000
        parcel["basic_info"]["acres"] = 50
        parcel["basic_info"]["price_per_acre"] = 10_000
        result = score_parcel(parcel, CRITERIA, enrichment)

        # Strong value_vs_comps should be a highlight
        assert result.highlights
        assert any(h["dimension"] == "value_vs_comps" for h in result.highlights)
        for h in result.highlights:
            assert "label" in h
            assert "detail" in h
            assert h["raw_score"] >= 0.75

    def test_drawbacks_below_threshold(self):
        """Dimensions scoring <= drawback_threshold appear in drawbacks."""
        enrichment = make_enrichment(
            cad_parcel=make_cad_parcel(parcel_id="TEST", improved=True),
            neighborhood_comps={"nbhd_code": "TEST", "count": 10, "median_market_per_acre": 5_000.0},
            landwatch_detail={"description": "", "days_on_market": 5, "price_history": []},
        )

        parcel = make_parcel()
        parcel["basic_info"]["price"] = 1_000_000
        parcel["basic_info"]["acres"] = 10
        result = score_parcel(parcel, CRITERIA, enrichment)

        # Poor value and low market signal should be drawbacks
        assert result.drawbacks
        for d in result.drawbacks:
            assert "label" in d
            assert "detail" in d
            assert d["raw_score"] <= 0.35

    def test_hard_zero_pins_to_top(self):
        """UDI disqualifier (raw_score=0.0) appears first in drawbacks."""
        # Need a proper CAD parcel with all required fields for developability dimension
        cad = {
            "parcel_id": "TEST",
            "parcel": {
                "parcel_id": "TEST",
                "compactness": 0.45,  # Required for developability
                "status": {
                    "udiPropFlag": "T",  # The disqualifier
                    "propSplitFromPID": None,
                    "protestCode": None,
                }
            }
        }
        enrichment = {
            "cad_parcel": cad,
            "neighborhood_comps": {"nbhd_code": "TEST", "count": 10, "median_market_per_acre": 10_000.0},
            "landwatch_detail": {"description": "creek", "days_on_market": 50, "price_history": []},
        }

        result = score_parcel(make_parcel(), CRITERIA, enrichment)

        # developability should be first in drawbacks with raw_score 0.0
        assert result.drawbacks
        # Find developability in drawbacks (it should be first due to zero pinning)
        dev_drawbacks = [d for d in result.drawbacks if d["dimension"] == "developability"]
        assert dev_drawbacks
        assert dev_drawbacks[0]["raw_score"] == 0.0
        # It should be first in the list
        assert result.drawbacks[0]["dimension"] == "developability"

    def test_not_assessed_populated_from_skipped(self):
        """Skipped dimensions appear in not_assessed with reasons."""
        enrichment = {
            "landwatch_detail": {
                "description": "creek",
                "days_on_market": 50,
                "price_history": [],
            }
        }

        result = score_parcel(make_parcel(), CRITERIA, enrichment)

        # CAD-only dimensions should be in not_assessed
        assert result.not_assessed
        assert any(na["dimension"] == "tax_burden" for na in result.not_assessed)
        for na in result.not_assessed:
            assert "label" in na
            assert "reason" in na
            assert na["reason"]  # non-empty

    def test_mid_range_scores_no_highlights_or_drawbacks(self):
        """When all dimensions are mid-range, both lists stay empty."""
        enrichment = make_enrichment(
            cad_parcel=make_cad_parcel(parcel_id="TEST"),
            neighborhood_comps={"nbhd_code": "TEST", "count": 10, "median_market_per_acre": 10_000.0},
            landwatch_detail={"description": "creek", "days_on_market": 50, "price_history": []},
        )

        parcel = make_parcel()
        parcel["basic_info"]["price"] = 500_000
        parcel["basic_info"]["acres"] = 50
        result = score_parcel(parcel, CRITERIA, enrichment)

        # All dimensions between 0.35 and 0.75 → no highlights or drawbacks
        all_mid_range = all(0.35 < d.raw_score < 0.75 for d in result.dimensions)
        if all_mid_range:
            assert result.highlights == []
            assert result.drawbacks == []
