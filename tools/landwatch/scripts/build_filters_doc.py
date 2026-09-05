"""Render ``landwatch/FILTERS.md`` from the filter catalog.

Run after changing :mod:`landwatch.filters` so the reference cannot drift from
the code::

    python scripts/build_filters_doc.py

The catalog is the source of truth; this script only groups and formats it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from landwatch.filters import FILTER_CATALOG, FilterKind, FilterSpec  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "landwatch" / "FILTERS.md"

# Reading order for a human deciding what to search for, rather than the
# catalog's own insertion order.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Where to search", ("state", "region", "county", "city")),
    (
        "What kind of property",
        (
            "property_types",
            "geographies",
            "has_residence",
            "housing_types",
            "land_uses",
            "activities",
        ),
    ),
    ("Price and size", ("price", "acres", "sqft", "beds_min", "baths_min")),
    ("Listing status", ("market_statuses", "sale_type", "price_reduction_days", "hoa")),
    ("Free text", ("keyword",)),
    (
        "Flags",
        (
            "owner_financing",
            "mineral_rights",
            "virtual_tour",
            "exterior_tour",
            "has_video",
            "custom_map",
        ),
    ),
    ("Paging and sorting", ("page", "sort_order_id")),
)

HEADER = """# LandWatch filter reference

Every filter LandWatch accepts and its possible values, covering places, property
types, terrain, keyword search and the numeric ranges.

This file is generated from `landwatch/filters.py` by
`scripts/build_filters_doc.py`. Edit the catalog, not this file.

The same data is available at runtime:

```bash
landwatch filters               # list every dimension
landwatch filters geographies   # values of one dimension
landwatch filters --json        # the whole catalog as JSON
```

## How a filter becomes a URL

Filters are path segments in a fixed order, not query parameters. LandWatch
treats the path as canonical and will not resolve segments given out of order,
so build URLs with `landwatch.url.build_path` rather than by hand:

```
/texas-land-for-sale/texoma-region/prop-types-3683/price-100000-1000000/acres-10-30/keyword-creek/page-2
 state              region        property types  price               acreage      keyword       page
```

Two details are easy to get wrong:

- **Property types combine with bitwise OR, not addition.** `waterfront` (3584)
  already contains `lakefront|oceanfront|riverfront`, so summing a set that
  includes it double-counts: LandWatch reads `{3, 32, 64, 512, 1024, 2048, 3584}`
  as 3683, not 7267.
- **Places take the bare name.** Pass `grayson`, not `grayson-county`; the
  `-county` and `-region` suffixes are added during URL construction.

## Finding places

State, region, county and city values are too numerous to list here. States,
regions and counties ship in `landwatch/data/geography.json` and resolve
offline; cities resolve through LandWatch's autocomplete endpoint, because the
site truncates its own per-state city facet at 300 entries.

```bash
landwatch locations              # all 51 states
landwatch locations --state tx   # every region and county in Texas
landwatch locations grayson      # resolve a name to its state and kind
```

`stateId` is the standard FIPS code, so state ids never need looking up.

"""


def _table(spec: FilterSpec) -> list[str]:
    entries = spec.values or spec.presets
    if not entries or spec.kind is FilterKind.BOOLEAN:
        return []

    has_id = any(entry.id is not None for entry in entries)
    header = "| Value | LandWatch label | URL segment |"
    divider = "| --- | --- | --- |"
    if has_id:
        header += " Id |"
        divider += " --- |"

    rows = [header, divider]
    for entry in entries:
        row = f"| `{entry.value}` | {entry.label} | `{entry.segment}` |"
        if has_id:
            row += f" {entry.id if entry.id is not None else ''} |"
        rows.append(row)
    rows.append("")
    return rows


def render() -> str:
    documented: set[str] = set()
    lines = [HEADER.rstrip(), ""]

    for heading, names in GROUPS:
        lines.append(f"## {heading}")
        lines.append("")
        for name in names:
            spec = FILTER_CATALOG[name]
            documented.add(name)

            section = f" (LandWatch section: *{spec.section}*)" if spec.section else ""
            lines.append(f"### `{name}`{section}")
            lines.append("")
            lines.append(spec.description)
            lines.append("")
            lines.append(f"- Kind: `{spec.kind.value}`")
            lines.append(f"- URL segment: `{spec.segment}`")
            if spec.presets and not spec.values:
                lines.append("- Any value is accepted; the table lists LandWatch's own buckets.")
            if spec.notes:
                lines.append(f"- Note: {spec.notes}")
            lines.append("")
            lines.extend(_table(spec))

    undocumented = set(FILTER_CATALOG) - documented
    if undocumented:
        raise SystemExit(
            "these filters are missing from GROUPS and would be left undocumented: "
            + ", ".join(sorted(undocumented))
        )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    OUTPUT_PATH.write_text(render())
    print(f"Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
