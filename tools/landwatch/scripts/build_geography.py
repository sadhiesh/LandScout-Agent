"""Generate ``landwatch/data/geography.json``, the bundled place dataset.

Run this to refresh the regions and counties that :mod:`landwatch.places`
resolves offline::

    python scripts/build_geography.py

It issues one state-level search per state (51 requests, throttled by the
client's own rate limiting) and reads the ``Region`` and ``County`` entries out
of each response's ``filterSections``, which is LandWatch's own enumeration of
the places it can search within that state. Those lists are untruncated but
cover only counties LandWatch has listings for, so a few sparse counties are
absent: Texas yields all 254 while Kansas yields 103 of 105.

Cities are deliberately excluded: LandWatch truncates its per-state city facet at
300 entries, so any bundled city list would be quietly incomplete. Cities resolve
through the autocomplete endpoint at runtime instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from landwatch.client import LandWatchClient, LandWatchError  # noqa: E402
from landwatch.vocab import STATE_ABBREVIATIONS, STATE_FIPS, state_segment  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "landwatch" / "data" / "geography.json"

# The filterSections headings holding places, mapped to the suffix LandWatch
# appends to each slug and that SearchCriteria does not want.
PLACE_SECTIONS: dict[str, tuple[str, str]] = {
    "Region": ("regions", "-region"),
    "County": ("counties", "-county"),
}


def _places(payload: dict[str, Any], section_name: str, suffix: str) -> list[dict[str, Any]]:
    """Extract one place section, reducing each link to name, slug and id."""
    for section in payload.get("filterSections") or []:
        if section.get("section") != section_name:
            continue

        places = []
        for link in section.get("filterLinks") or []:
            path = (link.get("relativeUrlPath") or "").rstrip("/")
            if not path:
                continue
            slug = path.rsplit("/", 1)[-1].removesuffix(suffix)
            if not slug:
                continue
            places.append(
                {
                    "name": link.get("displayText") or slug,
                    "slug": slug,
                    "id": link.get("id") or None,
                }
            )
        return sorted(places, key=lambda place: place["slug"])
    return []


def build(*, only: list[str] | None = None) -> dict[str, Any]:
    abbreviations = only or sorted(STATE_FIPS)
    states: dict[str, Any] = {}
    failures: list[str] = []

    with LandWatchClient() as client:
        for index, abbreviation in enumerate(abbreviations, start=1):
            slug = STATE_ABBREVIATIONS[abbreviation]
            path = f"/{state_segment(abbreviation)}"
            try:
                payload = client.search_payload(path)
            except LandWatchError as exc:
                print(f"  [{index:2}/{len(abbreviations)}] {abbreviation}: FAILED {exc}")
                failures.append(abbreviation)
                continue

            entry: dict[str, Any] = {
                "name": slug.replace("-", " ").title(),
                "slug": slug,
                "id": STATE_FIPS[abbreviation],
            }
            for section_name, (key, suffix) in PLACE_SECTIONS.items():
                entry[key] = _places(payload, section_name, suffix)

            states[abbreviation] = entry
            print(
                f"  [{index:2}/{len(abbreviations)}] {abbreviation}: "
                f"{len(entry['regions']):3} regions, {len(entry['counties']):4} counties"
            )

    if failures:
        print(f"\nWARNING: {len(failures)} state(s) failed: {', '.join(failures)}")

    return {
        # timezone.utc rather than dt.UTC, which needs Python 3.11.
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "LandWatch filterSections from state-level search responses",
        "note": (
            "Cities are excluded because LandWatch caps its per-state city facet at "
            "300 entries; resolve cities via landwatch.places.resolve()."
        ),
        "states": states,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        action="append",
        dest="states",
        metavar="ABBR",
        help="Limit to specific states, e.g. --state tx --state co. Repeatable.",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_PATH, help=f"Output path (default: {OUTPUT_PATH})"
    )
    args = parser.parse_args()

    only = None
    if args.states:
        only = [state.strip().lower() for state in args.states]
        unknown = [state for state in only if state not in STATE_FIPS]
        if unknown:
            parser.error(f"unknown state abbreviation(s): {', '.join(unknown)}")

    print(f"Fetching place data for {len(only or STATE_FIPS)} state(s)...")
    data = build(only=only)
    if not data["states"]:
        print("No data fetched; leaving the existing file untouched.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")

    regions = sum(len(entry["regions"]) for entry in data["states"].values())
    counties = sum(len(entry["counties"]) for entry in data["states"].values())
    size_kb = args.output.stat().st_size / 1024
    print(
        f"\nWrote {args.output} ({size_kb:.0f} KB): "
        f"{len(data['states'])} states, {regions} regions, {counties} counties"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
