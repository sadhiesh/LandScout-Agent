"""Offline tests for FEMA NFHL flood tool."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from fema_flood import FEMAFloodError, get_fema_flood_from_geometry


class TestResolveWkid:
    """Test WKID resolution."""
    
    def test_uses_geometry_embedded_wkid(self):
        """Prefer spatialReference.wkid from geometry."""
        geometry = {
            "rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]],
            "spatialReference": {"wkid": 2276},
        }
        with patch("fema_flood.fema_flood._intersect_query") as mock_query:
            mock_query.return_value = {"features": []}
            get_fema_flood_from_geometry(geometry)
            # Check that _intersect_query was called with wkid=2276
            assert mock_query.call_args[0][2] == 2276
    
    def test_uses_latest_wkid_if_wkid_missing(self):
        """Fall back to latestWkid if wkid not present."""
        geometry = {
            "rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]],
            "spatialReference": {"latestWkid": 2276},
        }
        with patch("fema_flood.fema_flood._intersect_query") as mock_query:
            mock_query.return_value = {"features": []}
            get_fema_flood_from_geometry(geometry)
            assert mock_query.call_args[0][2] == 2276
    
    def test_uses_explicit_wkid_parameter(self):
        """Use explicit wkid parameter if geometry lacks SR."""
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]}
        with patch("fema_flood.fema_flood._intersect_query") as mock_query:
            mock_query.return_value = {"features": []}
            get_fema_flood_from_geometry(geometry, wkid=4326)
            assert mock_query.call_args[0][2] == 4326
    
    def test_raises_if_no_wkid_available(self):
        """Raise if no WKID can be determined."""
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]}
        with pytest.raises(FEMAFloodError, match="Cannot determine spatial reference"):
            get_fema_flood_from_geometry(geometry)


class TestSentinelHandling:
    """Test -9999 sentinel normalization."""
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_cleans_minus_9999_bfe(self, mock_query):
        """Normalize -9999 to None for STATIC_BFE."""
        mock_query.side_effect = [
            {
                "features": [
                    {
                        "attributes": {
                            "FLD_ZONE": "AE",
                            "ZONE_SUBTY": None,
                            "SFHA_TF": "T",
                            "STATIC_BFE": -9999,
                        },
                        "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                    }
                ]
            },
            {"features": []},  # FIRM
            {"features": []},  # LOMRs
            {"features": []},  # LOMAs
        ]
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_fema_flood_from_geometry(geometry)
        
        assert result["details"]["static_bfe"] is None
        assert result["details"]["raw"][0]["bfe"] is None


class TestFloodwayDetection:
    """Test floodway detection from ZONE_SUBTY."""
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_detects_floodway_from_zone_subty(self, mock_query):
        """Floodway flag set when ZONE_SUBTY='FLOODWAY'."""
        mock_query.side_effect = [
            {
                "features": [
                    {
                        "attributes": {
                            "FLD_ZONE": "AE",
                            "ZONE_SUBTY": "FLOODWAY",
                            "SFHA_TF": "T",
                            "STATIC_BFE": 500.0,
                        },
                        "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                    }
                ]
            },
            {"features": []},
            {"features": []},
            {"features": []},
        ]
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_fema_flood_from_geometry(geometry)
        
        assert result["details"]["floodway"] is True
        assert result["investment_impact"]["risk_tier"] == "high"


class TestMultiPolygonAggregation:
    """Test handling of multiple intersecting flood zones."""
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_aggregates_multiple_zones(self, mock_query):
        """Aggregate multiple flood zones into all_zones and worst_zone."""
        mock_query.side_effect = [
            {
                "features": [
                    {
                        "attributes": {
                            "FLD_ZONE": "AE",
                            "ZONE_SUBTY": None,
                            "SFHA_TF": "T",
                            "STATIC_BFE": 500.0,
                        },
                        "geometry": {"rings": [[[0, 0], [0.5, 0.5], [0.5, 0], [0, 0]]]},
                    },
                    {
                        "attributes": {
                            "FLD_ZONE": "X",
                            "ZONE_SUBTY": None,
                            "SFHA_TF": "F",
                            "STATIC_BFE": -9999,
                        },
                        "geometry": {"rings": [[[0.5, 0], [1, 1], [1, 0], [0.5, 0]]]},
                    },
                ]
            },
            {"features": []},
            {"features": []},
            {"features": []},
        ]
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_fema_flood_from_geometry(geometry, parcel_acres=10.0)
        
        assert "AE" in result["details"]["all_zones"]
        assert "X" in result["details"]["all_zones"]
        assert result["details"]["worst_zone"] == "AE"  # Higher risk
        assert len(result["details"]["raw"]) == 2


class TestEmptyResult:
    """Test handling of no flood zone overlap."""
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_no_flood_zone_returns_false(self, mock_query):
        """No features returns in_flood_zone=False."""
        mock_query.return_value = {"features": []}
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_fema_flood_from_geometry(geometry)
        
        assert result["in_flood_zone"] is False
        assert result["details"]["worst_zone"] is None
        assert result["details"]["all_zones"] == []
        assert result["investment_impact"]["risk_tier"] == "none"


class TestErrorHandling:
    """Test error handling."""
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_raises_on_arcgis_error(self, mock_query):
        """Raise FEMAFloodError on ArcGIS error response."""
        mock_query.side_effect = FEMAFloodError("ArcGIS error: Bad request")
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        with pytest.raises(FEMAFloodError, match="Bad request"):
            get_fema_flood_from_geometry(geometry)
    
    def test_raises_on_missing_rings(self):
        """Raise on geometry without rings."""
        geometry = {"spatialReference": {"wkid": 2276}}
        with pytest.raises(FEMAFloodError, match="no 'rings' key"):
            get_fema_flood_from_geometry(geometry)


class TestFirmPanelAndLomrs:
    """Test FIRM panel and LOMR/LOMA extraction."""
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_extracts_firm_panel(self, mock_query):
        """Extract FIRM_PAN from layer 3."""
        mock_query.side_effect = [
            {"features": []},  # Zones
            {"features": [{"attributes": {"FIRM_PAN": "48085C0390K"}}]},  # FIRM
            {"features": []},  # LOMRs
            {"features": []},  # LOMAs
        ]
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_fema_flood_from_geometry(geometry)
        
        assert result["details"]["firm_panel"] == "48085C0390K"
    
    @patch("fema_flood.fema_flood._intersect_query")
    def test_extracts_lomrs_and_lomas(self, mock_query):
        """Extract LOMRs and LOMAs."""
        mock_query.side_effect = [
            {"features": []},
            {"features": []},
            {
                "features": [
                    {"attributes": {"CASE_NO": "20-123", "EFF_DATE": "2020-01-15", "STATUS": "Effective"}}
                ]
            },
            {
                "features": [
                    {
                        "attributes": {
                            "CASENUMBER": "LOMA-456",
                            "DETERMINATIONTYPE": "LOMA",
                            "OUTCOME": "Property Removed",
                        }
                    }
                ]
            },
        ]
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_fema_flood_from_geometry(geometry)
        
        assert len(result["details"]["lomrs"]) == 1
        assert result["details"]["lomrs"][0]["case_no"] == "20-123"
        assert len(result["details"]["lomas"]) == 1
        assert result["details"]["lomas"][0]["case_number"] == "LOMA-456"
