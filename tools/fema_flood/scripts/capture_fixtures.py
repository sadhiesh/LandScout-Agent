"""Capture fixtures from live FEMA NFHL service for offline tests.

This is the ONLY script permitted to hit the live service. Run manually when
the service changes or when adding new test cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "collin_cad"))

from fema_flood import get_fema_flood_from_geometry
from collin_cad import get_collin_parcel_data

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def capture_fixture(name: str, prop_id: int):
    """Capture one fixture by fetching geometry from Collin CAD first."""
    print(f"Capturing {name} (PROP_ID {prop_id})...")
    try:
        # Get parcel geometry from Collin CAD
        parcel_data = get_collin_parcel_data(property_id=prop_id)
        parcel = parcel_data.get("parcel")
        if not parcel:
            print(f"  ERROR: Parcel not found")
            return
        
        geometry = parcel.get("geometry")
        if not geometry:
            print(f"  ERROR: No geometry in parcel")
            return
        
        acres = parcel.get("land", {}).get("landSizeAcres")
        
        # Query FEMA flood
        result = get_fema_flood_from_geometry(geometry, parcel_acres=acres)
        
        # Save fixture
        fixture = {
            "prop_id": prop_id,
            "geometry": geometry,
            "parcel_acres": acres,
            "result": result,
        }
        fixture_path = FIXTURES_DIR / f"{name}.json"
        fixture_path.write_text(json.dumps(fixture, indent=2, default=str))
        print(f"  -> {fixture_path}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Capture all fixtures."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    
    # PROP_ID 46: Zone X (low risk)
    capture_fixture("prop_id_46_zone_x", prop_id=46)
    
    # PROP_ID 1912050: AE/FLOODWAY (high risk)
    capture_fixture("prop_id_1912050_ae_floodway", prop_id=1912050)
    
    print("\nFEMA flood fixture capture complete!")


if __name__ == "__main__":
    main()
