"""Offline tests for Collin County floodplain tool."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from collin_flood import CollinFloodError, get_collin_floodplain_from_geometry


class TestResolveWkid:
    """Test WKID resolution."""
    
    def test_uses_geometry_embedded_wkid(self):
        """Prefer spatialReference.wkid from geometry."""
        geometry = {
            "rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]],
            "spatialReference": {"wkid": 2276},
        }
        with patch("collin_flood.collin_flood._intersect_query") as mock_query:
            mock_query.return_value = {"features": []}
            get_collin_floodplain_from_geometry(geometry)
            # Check that _intersect_query was called with wkid=2276
            assert mock_query.call_args[0][2] == 2276
    
    def test_uses_explicit_wkid_parameter(self):
        """Use explicit wkid parameter if geometry lacks SR."""
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]}
        with patch("collin_flood.collin_flood._intersect_query") as mock_query:
            mock_query.return_value = {"features": []}
            get_collin_floodplain_from_geometry(geometry, wkid=4326)
            assert mock_query.call_args[0][2] == 4326
    
    def test_raises_if_no_wkid_available(self):
        """Raise if no WKID can be determined."""
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]}
        with pytest.raises(CollinFloodError, match="Cannot determine spatial reference"):
            get_collin_floodplain_from_geometry(geometry)


class TestSentinelHandling:
    """Test -9999 sentinel normalization."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_cleans_minus_9999_bfe(self, mock_query):
        """Normalize -9999 to None for STATIC_BFE."""
        mock_query.return_value = {
            "features": [
                {
                    "attributes": {
                        "FLD_ZONE": "AE",
                        "FLOODWAY": "N",
                        "SFHA_TF": "T",
                        "STATIC_BFE": -9999,
                    },
                    "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                }
            ]
        }
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry)
        
        assert result["details"]["bfe"] is None
        assert result["details"]["raw"][0]["bfe"] is None


class TestFloodwayDetection:
    """Test floodway detection from FLOODWAY field."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_detects_floodway_from_field(self, mock_query):
        """Floodway flag set when FLOODWAY='Y'."""
        mock_query.return_value = {
            "features": [
                {
                    "attributes": {
                        "FLD_ZONE": "AE",
                        "FLOODWAY": "Y",
                        "SFHA_TF": "T",
                        "STATIC_BFE": 500.0,
                    },
                    "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                }
            ]
        }
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry)
        
        assert result["details"]["floodway"] is True
        assert result["details"]["raw"][0]["floodway"] is True


class TestMultiPolygonAggregation:
    """Test handling of multiple intersecting floodplain zones."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_aggregates_multiple_zones(self, mock_query):
        """Aggregate multiple zones into all_zones and flood_zone."""
        mock_query.return_value = {
            "features": [
                {
                    "attributes": {
                        "FLD_ZONE": "AE",
                        "FLOODWAY": "N",
                        "SFHA_TF": "T",
                        "STATIC_BFE": 500.0,
                    },
                    "geometry": {"rings": [[[0, 0], [0.5, 0.5], [0.5, 0], [0, 0]]]},
                },
                {
                    "attributes": {
                        "FLD_ZONE": "X",
                        "FLOODWAY": "N",
                        "SFHA_TF": "F",
                        "STATIC_BFE": -9999,
                    },
                    "geometry": {"rings": [[[0.5, 0], [1, 1], [1, 0], [0.5, 0]]]},
                },
            ]
        }
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry, parcel_acres=10.0)
        
        assert "AE" in result["details"]["all_zones"]
        assert "X" in result["details"]["all_zones"]
        assert result["details"]["flood_zone"] == "AE"  # Higher risk
        assert len(result["details"]["raw"]) == 2


class TestEmptyResult:
    """Test handling of no floodplain overlap."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_no_floodplain_returns_false(self, mock_query):
        """No features returns floodplain=False."""
        mock_query.return_value = {"features": []}
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry)
        
        assert result["floodplain"] is False
        assert result["details"]["flood_zone"] is None
        assert result["details"]["all_zones"] == []
        assert result["details"]["coverage"]["affected_fraction"] == 0.0


class TestErrorHandling:
    """Test error handling."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_raises_on_arcgis_error(self, mock_query):
        """Raise CollinFloodError on ArcGIS error response."""
        mock_query.side_effect = CollinFloodError("ArcGIS error: Bad request")
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        with pytest.raises(CollinFloodError, match="Bad request"):
            get_collin_floodplain_from_geometry(geometry)
    
    def test_raises_on_missing_rings(self):
        """Raise on geometry without rings."""
        geometry = {"spatialReference": {"wkid": 2276}}
        with pytest.raises(CollinFloodError, match="no 'rings' key"):
            get_collin_floodplain_from_geometry(geometry)


class TestFirmPanelNull:
    """Test that firm_panel is always None."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_firm_panel_always_none(self, mock_query):
        """firm_panel is always None for Collin layer."""
        mock_query.return_value = {
            "features": [
                {
                    "attributes": {
                        "FLD_ZONE": "AE",
                        "FLOODWAY": "N",
                        "SFHA_TF": "T",
                        "STATIC_BFE": 500.0,
                    },
                    "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                }
            ]
        }
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry)
        
        assert result["details"]["firm_panel"] is None


class TestAffectedAcreage:
    """Test affected acreage calculation."""
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_calculates_affected_acres(self, mock_query):
        """Calculate affected_acres when parcel_acres provided."""
        mock_query.return_value = {
            "features": [
                {
                    "attributes": {
                        "FLD_ZONE": "AE",
                        "FLOODWAY": "N",
                        "SFHA_TF": "T",
                        "STATIC_BFE": 500.0,
                    },
                    "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                }
            ]
        }
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry, parcel_acres=10.0)
        
        # Affected fraction should be computed (mocked geometry has same rings, so ~100%)
        assert result["details"]["coverage"]["affected_fraction"] > 0
        assert result["details"]["coverage"]["affected_acres"] is not None
    
    @patch("collin_flood.collin_flood._intersect_query")
    def test_null_affected_acres_without_parcel_acres(self, mock_query):
        """affected_acres is None when parcel_acres not provided."""
        mock_query.return_value = {
            "features": [
                {
                    "attributes": {
                        "FLD_ZONE": "AE",
                        "FLOODWAY": "N",
                        "SFHA_TF": "T",
                        "STATIC_BFE": 500.0,
                    },
                    "geometry": {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]]},
                }
            ]
        }
        
        geometry = {"rings": [[[0, 0], [1, 1], [1, 0], [0, 0]]], "spatialReference": {"wkid": 2276}}
        result = get_collin_floodplain_from_geometry(geometry)
        
        assert result["details"]["coverage"]["affected_acres"] is None
