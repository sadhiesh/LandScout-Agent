"""Capture fixtures from live Collin CAD service for offline tests.

This is the ONLY script permitted to hit the live service. Run manually when
the service changes or when adding new test cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collin_cad import get_collin_parcel_data

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def capture_fixture(name: str, **kwargs):
    """Capture one fixture."""
    print(f"Capturing {name}...")
    try:
        result = get_collin_parcel_data(**kwargs)
        fixture_path = FIXTURES_DIR / f"{name}.json"
        fixture_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"  -> {fixture_path}")
    except Exception as e:
        print(f"  ERROR: {e}")


def main():
    """Capture all fixtures."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Property ID lookup
    capture_fixture("prop_id_983555", property_id=983555)
    
    # Parcel ID lookup
    capture_fixture("geo_id_R-6782-000-0140-1", parcel_id="R-6782-000-0140-1")
    
    # Lat/lon point query
    capture_fixture("latlon_33.0_-96.0", latitude=33.0, longitude=-96.0)
    
    # Address lookup (ambiguous case)
    capture_fixture("address_1200_plano", address="1200 Main St", city="Plano")
    
    # Not found
    capture_fixture("not_found", property_id=999999999)
    
    print("\nFixture capture complete!")


if __name__ == "__main__":
    main()
