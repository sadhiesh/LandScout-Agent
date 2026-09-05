"""Offline tests for Collin CAD client against captured fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from collin_cad import (
    CollinCADError,
    ParcelNotFound,
    ParcelLookupInput,
    get_collin_parcel_data,
    get_neighborhood_comps,
    run_parcel_lookup,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


# A real CCAD row, trimmed to the attributes the shaping step reads. Names here
# are the live ones — the whole point of these tests is that a typo in a field
# group shows up as a failure rather than as a block of nulls.
REAL_ATTRS = {
    "PROP_ID": 2121800,
    "geoID": "R-6741-004-0570-1",
    "propYear": 2027,
    "propSubType": "Residential",
    "propCategoryCode": "E",
    "nbhdCode": "SMCR",
    "legalDescription": "ABS A0741 THOMAS A RHODES SURVEY, SHEET 4, TRACT 57, 15.538 ACRES",
    "legalAbsSubName": "THOMAS A RHODES SURVEY",
    "legalAbsSubBlock": "4",
    "legalAbsSubLot": "57",
    "entityCodes": "GCN,JCN,SMC,ECC1",
    "entitySchoolCode": "SMC",
    "entityCityCode": None,
    "entityMUD": "F",
    "entityTIF": "F",
    "entitySBCL": "F",
    "situsBldgNum": "4195",
    "situsStreetName": "COUNTY ROAD 1001",
    "situsCity": "MCKINNEY",
    "situsZip": "75071",
    "situsConcat": "4195 COUNTY ROAD 1001 , MCKINNEY, TX 75071",
    "ownerName": "WILLETT JEFFREY MICHAEL",
    "ownerAddrLine1": "4195 COUNTY ROAD 1001",
    "ownerAddrCity": "MCKINNEY",
    "ownerAddrState": "TX",
    "ownerAddrZip": "75071-0620",
    "deedTypeCd": "SWDNL",
    "deedNum": "20101012001098060",
    "deedEffDate": 1285113600000,
    "deedFileDate": 1286841600000,
    "imprvYearBuilt": 1999,
    "imprvClassCd": "R04+",
    "imprvMainArea": 2506,
    "imprvPoolFlag": "T",
    "landTypeCode": "D1IP",
    "landSizeAcres": 15.538,
    "landSizeSqft": 676835,
    "landAgAcres": 14.538,
    "landCategoryCodes": "D1,E",
    "exemptCodes": "HS",
    "exemptHmstdFlag": "T",
    "protestCode": None,
    "udiPropFlag": "F",
    "propSplitFromPID": None,
    "prevValMarket": 1296978,
    "prevValLand": 823514,
    "prevValImprv": 473464,
    "prevValAgLoss": 769002,
    "prevValAppraised": 527976,
    "prevValAssessed": 527976,
    "Shape__Area": 655779.416015625,
    "Shape__Length": 5996.99602256548,
}


class TestParcelLookupInput:
    """Test input validation."""
    
    def test_exactly_one_lookup_method_required(self):
        """Can't provide multiple lookup methods."""
        with pytest.raises(ValueError, match="exactly one"):
            ParcelLookupInput(property_id=123, parcel_id="R-123")
    
    def test_latlon_requires_both(self):
        """Latitude and longitude must be provided together."""
        with pytest.raises(ValueError, match="both be provided"):
            ParcelLookupInput(latitude=33.0)
        
        with pytest.raises(ValueError, match="both be provided"):
            ParcelLookupInput(longitude=-96.0)
    
    def test_latlon_counts_as_one_method(self):
        """Lat/lon together is one method."""
        # Should succeed
        payload = ParcelLookupInput(latitude=33.0, longitude=-96.0)
        assert payload.latitude == 33.0
        assert payload.longitude == -96.0
    
    def test_forbids_extra_fields(self):
        """Extra fields are rejected."""
        with pytest.raises(ValueError):
            ParcelLookupInput(property_id=123, unknown_field="value")


class TestPropertyIdLookup:
    """Test property ID lookup (mocked)."""
    
    @patch("collin_cad.collin_cad._query")
    def test_returns_shaped_parcel(self, mock_query):
        """Property ID lookup returns shaped parcel data."""
        # Mock response - _query now returns (features, spatial_ref)
        mock_query.return_value = ([{
            "attributes": {
                "PROP_ID": 983555,
                "geoID": "R-6782-000-0140-1",
                "entityCityCode": "CMC",
                "situsBldgNum": "123",
                "situsStreetName": "Main St",
                "situsCity": "McKinney",
                "ownerName": "Test Owner",
                "landSizeAcres": 10.0,
                "prevValMarket": 100000,
                "propYear": 2027,
                "Shape__Area": 435600,  # 10 acres in sq ft
            },
            "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
            "centroid": {"x": -96.5, "y": 33.5},
        }], {"wkid": 102738, "latestWkid": 2276})
        
        result = get_collin_parcel_data(property_id=983555)
        
        assert result["parcel"]["property_id"] == 983555
        assert result["parcel"]["parcel_id"] == "R-6782-000-0140-1"
        assert result["parcel"]["city"] == "McKinney"
        assert result["parcel"]["gis_acres"] == pytest.approx(10.0)
        assert result["parcel"]["centroid"] == {"lat": 33.5, "lon": -96.5}
        assert result["warnings"] == []


class TestAgentWrapper:
    """Test the agent/MCP wrapper."""
    
    @patch("collin_cad.collin_cad._query")
    def test_never_raises_returns_json(self, mock_query):
        """Agent wrapper returns JSON, never raises."""
        mock_query.side_effect = Exception("Simulated failure")
        
        result_json = run_parcel_lookup(property_id=123)
        result = json.loads(result_json)
        
        assert "error" in result
        assert "Exception" in result["error"]


class TestValuationFallback:
    """Test current -> notice -> previous valuation fallback."""
    
    @patch("collin_cad.collin_cad._query")
    def test_uses_previous_when_current_null(self, mock_query):
        """Falls back to prevVal when currVal is null."""
        mock_query.return_value = ([{
            "attributes": {
                "PROP_ID": 123,
                "geoID": "R-123",
                "currValMarket": None,
                "noticeValMarket": None,
                "prevValMarket": 50000,
                "propYear": 2027,
            },
            "geometry": None,
        }], {"wkid": 102738, "latestWkid": 2276})
        
        result = get_collin_parcel_data(property_id=123)
        
        assert result["parcel"]["valuation"]["market"] == 50000
        assert result["parcel"]["valuation_basis"] == "previous"
        assert result["parcel"]["valuation_year"] == 2026  # propYear - 1


class TestCityDetermination:
    """Test city derivation from entityCityCode only."""
    
    @patch("collin_cad.collin_cad._query")
    def test_uses_entity_city_code_not_situs(self, mock_query):
        """City comes from entityCityCode, not situsCity."""
        mock_query.return_value = ([{
            "attributes": {
                "PROP_ID": 123,
                "geoID": "R-123",
                "entityCityCode": "CFR",  # Frisco
                "situsCity": "PLANO",  # Wrong!
            },
            "geometry": None,
        }], {"wkid": 102738, "latestWkid": 2276})
        
        result = get_collin_parcel_data(property_id=123)
        
        assert result["parcel"]["city"] == "Frisco"
    
    @patch("collin_cad.collin_cad._query")
    def test_unincorporated_when_no_entity_code(self, mock_query):
        """Returns 'Unincorporated' when entityCityCode is null."""
        mock_query.return_value = ([{
            "attributes": {
                "PROP_ID": 123,
                "geoID": "R-123",
                "entityCityCode": None,
                "situsCity": "MCKINNEY",
            },
            "geometry": None,
        }], {"wkid": 102738, "latestWkid": 2276})
        
        result = get_collin_parcel_data(property_id=123)
        
        assert result["parcel"]["city"] == "Unincorporated (Collin County)"


class TestAmbiguousResults:
    """Test handling of multiple matches."""
    
    @patch("collin_cad.collin_cad._query")
    def test_returns_first_plus_matches(self, mock_query):
        """Multiple results return first + matches array + warning."""
        mock_query.return_value = ([
            {
                "attributes": {"PROP_ID": 1, "geoID": "R-1"},
                "geometry": None,
            },
            {
                "attributes": {"PROP_ID": 2, "geoID": "R-2"},
                "geometry": None,
            },
        ], {"wkid": 102738, "latestWkid": 2276})
        
        result = get_collin_parcel_data(address="123 Main St")
        
        assert result["parcel"]["property_id"] == 1
        assert len(result["matches"]) == 2
        assert "Ambiguous" in result["warnings"][0]


class TestShapedBlocks:
    """The field groups must match live attribute names, not plausible ones."""

    @pytest.fixture
    def parcel(self):
        with patch("collin_cad.collin_cad._query") as mock_query:
            mock_query.return_value = ([{
                "attributes": dict(REAL_ATTRS),
                "geometry": None,
            }], {"wkid": 102738, "latestWkid": 2276})
            return get_collin_parcel_data(property_id=2121800)["parcel"]

    def test_owner_block_populates(self, parcel):
        """A mailing* name here would silently yield an all-null owner block."""
        assert parcel["owner"]["ownerName"] == "WILLETT JEFFREY MICHAEL"
        assert parcel["owner"]["ownerAddrLine1"] == "4195 COUNTY ROAD 1001"
        assert parcel["owner"]["ownerAddrState"] == "TX"

    def test_legal_and_deed_blocks_populate(self, parcel):
        assert "THOMAS A RHODES SURVEY" in parcel["legal"]["legalDescription"]
        assert parcel["legal"]["legalAbsSubLot"] == "57"
        assert parcel["deed"]["type_code"] == "SWDNL"
        assert parcel["deed"]["number"] == "20101012001098060"
        assert parcel["deed"]["effective_date"] == "2010-09-21"

    def test_situs_uses_situs_zip_not_zipcode(self, parcel):
        assert parcel["situs"]["situsZip"] == "75071"
        assert parcel["situs"]["situsBldgNum"] == "4195"

    def test_entity_and_status_blocks_populate(self, parcel):
        assert parcel["entity"]["entityCodes"] == "GCN,JCN,SMC,ECC1"
        assert parcel["entity"]["entityMUD"] == "F"
        assert parcel["status"]["nbhdCode"] == "SMCR"
        assert parcel["status"]["exemptHmstdFlag"] == "T"
        assert parcel["status"]["udiPropFlag"] == "F"

    def test_land_block_drops_nonexistent_field(self, parcel):
        assert parcel["land"]["landTypeCode"] == "D1IP"
        assert parcel["land"]["landCategoryCodes"] == "D1,E"
        assert "landValMarket" not in parcel["land"]

    def test_valuation_has_no_phantom_ag_key(self, parcel):
        """There is no {prefix}Ag field; the ag figure is {prefix}AgLoss."""
        assert "ag" not in parcel["valuation"]
        assert parcel["valuation"]["ag_loss"] == 769002
        assert parcel["valuation"]["appraised"] == 527976


class TestDerivedFields:
    """Derived signals the scorer reads."""

    @pytest.fixture
    def parcel(self):
        with patch("collin_cad.collin_cad._query") as mock_query:
            mock_query.return_value = ([{
                "attributes": dict(REAL_ATTRS),
                "geometry": None,
            }], {"wkid": 102738, "latestWkid": 2276})
            return get_collin_parcel_data(property_id=2121800)["parcel"]

    def test_ag_loss_ratio(self, parcel):
        assert parcel["ag_exempt"] is True
        assert parcel["ag_loss_ratio"] == pytest.approx(769002 / 1296978)

    def test_compactness_flags_an_irregular_tract(self, parcel):
        # 4*pi*A/P^2 for this polygon is well under the 0.6 "clean shape" mark.
        assert parcel["compactness"] == pytest.approx(0.229, abs=0.01)

    def test_owner_occupied_when_mailing_matches_situs(self, parcel):
        assert parcel["owner_occupied"] is True

    def test_owner_occupied_false_for_absentee(self):
        attrs = dict(REAL_ATTRS, ownerAddrLine1="1 ELSEWHERE LANE")
        with patch("collin_cad.collin_cad._query") as mock_query:
            mock_query.return_value = (
                [{"attributes": attrs, "geometry": None}],
                {"wkid": 102738, "latestWkid": 2276},
            )
            parcel = get_collin_parcel_data(property_id=2121800)["parcel"]
        assert parcel["owner_occupied"] is False

    def test_acreage_variance_between_gis_and_appraised(self, parcel):
        # 15.05 GIS acres against 15.538 appraised is a ~3% gap.
        assert parcel["acreage_variance"] == pytest.approx(0.031, abs=0.005)

    def test_held_years_from_deed(self, parcel):
        assert parcel["held_years"] > 15

    def test_market_per_acre_uses_previous_year_valuation(self, parcel):
        assert parcel["valuation_basis"] == "previous"
        assert parcel["valuation_year"] == 2026
        assert parcel["market_per_acre"] == pytest.approx(1296978 / 15.538)


class TestNeighborhoodComps:
    """Median value per acre across a nbhdCode cohort."""

    @staticmethod
    def _cohort(n: int, market: int = 100000, acres: float = 10.0):
        return [
            {"attributes": {
                "PROP_ID": i,
                "landSizeAcres": acres,
                "prevValMarket": market,
                "prevValLand": market // 2,
            }}
            for i in range(n)
        ]

    @patch("collin_cad.collin_cad._query")
    def test_returns_medians_for_a_full_cohort(self, mock_query):
        mock_query.return_value = (self._cohort(8), None)

        result = get_neighborhood_comps(nbhd_code="SMCR", land_type_code="D1IP")

        assert result["count"] == 8
        assert result["median_market_per_acre"] == pytest.approx(10000.0)
        assert result["median_land_per_acre"] == pytest.approx(5000.0)
        assert result["nbhd_code"] == "SMCR"
        assert result["warnings"] == []

    @patch("collin_cad.collin_cad._query")
    def test_withholds_median_for_a_thin_cohort(self, mock_query):
        mock_query.return_value = (self._cohort(3), None)

        result = get_neighborhood_comps(nbhd_code="SMCR")

        assert result["count"] == 3
        assert result["median_market_per_acre"] is None
        assert "minimum" in result["warnings"][0]

    @patch("collin_cad.collin_cad._query")
    def test_empty_cohort_is_not_an_error(self, mock_query):
        mock_query.return_value = ([], None)

        result = get_neighborhood_comps(nbhd_code="NOPE")

        assert result["count"] == 0
        assert result["median_market_per_acre"] is None

    @patch("collin_cad.collin_cad._query")
    def test_flags_a_truncated_cohort(self, mock_query):
        from collin_cad.collin_cad import MAX_RECORD_COUNT

        mock_query.return_value = (self._cohort(MAX_RECORD_COUNT), None)

        result = get_neighborhood_comps(nbhd_code="SMCR")

        assert any("truncated" in w for w in result["warnings"])

    @patch("collin_cad.collin_cad._query")
    def test_skips_parcels_with_no_valuation(self, mock_query):
        cohort = self._cohort(6)
        cohort.append({"attributes": {"PROP_ID": 99, "landSizeAcres": 10.0}})
        mock_query.return_value = (cohort, None)

        result = get_neighborhood_comps(nbhd_code="SMCR")

        assert result["count"] == 6

    def test_requires_a_neighborhood_code(self):
        with pytest.raises(CollinCADError, match="nbhd_code is required"):
            get_neighborhood_comps(nbhd_code="")


# Fixture-based integration tests (optional, require fixtures)
@pytest.mark.skipif(
    not FIXTURES_DIR.exists(),
    reason="Fixtures not captured yet; run scripts/capture_fixtures.py"
)
class TestWithFixtures:
    """Integration tests against captured fixtures."""
    
    # These would use actual fixtures if available
    pass
