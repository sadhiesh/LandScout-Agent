# LandWatch Land Search Client

A Python client that turns structured land-buying criteria into a
[LandWatch](https://www.landwatch.com) search URL, fetches the matching listings, and
returns them as typed Pydantic models. Usable as a library, a CLI, or an agent tool.

## Installation

The HTTP/2 extra is required rather than optional, because LandWatch's CDN rejects
HTTP/1.1 requests outright:

```bash
uv pip install -e .      # or: pip install -e .
```

To expose the search as a CrewAI tool as well:

```bash
pip install -e ".[crewai]"
```

## Library usage

```python
from landwatch import SearchCriteria, PropertyType, search

result = search(SearchCriteria(
    state="texas",
    county="grayson",
    price_min=200_000,
    price_max=800_000,
    acres_min=5,
    acres_max=50,
    property_types=PropertyType.FARMS_AND_RANCHES | PropertyType.UNDEVELOPED,
))

print(result.url)          # the URL that was built and fetched
print(result.total_count)  # total matches across all pages

for listing in result.listings:
    print(listing.price_display, listing.acres_display, listing.city, listing.url)
```

Fetch more than one page, or full detail for a single listing:

```python
from landwatch import collect, get_detail

merged = collect(criteria, max_pages=4, max_listings=80)

detail = get_detail(merged.listings[0].property_id)
for event in detail.price_history:
    print(event.date, event.event, event.price)
```

Build a URL without making any request:

```python
from landwatch import build_url
build_url(SearchCriteria(state="colorado", property_types=PropertyType.HUNTING, acres_min=40))
# https://www.landwatch.com/colorado-land-for-sale/prop-types-128/acres-over-40
```

Search by terrain and free text as well as by place:

```python
from landwatch import Geography, SearchCriteria, search

search(SearchCriteria(
    state="colorado",
    geographies=[Geography.MOUNTAIN, Geography.OFF_GRID],
    keyword="creek frontage",
    acres_min=40,
))
```

## Filters and places

[FILTERS.md](FILTERS.md) is the full reference: every filter dimension, its URL
segment and its possible values. The same catalog is available at runtime, and is
what drives the CLI help and the agent tool descriptions:

```python
from landwatch import filters

filters.FILTER_CATALOG["geographies"].value_names
# ['beachfront', 'desert', 'island', 'lakefront', 'mountain', 'off-grid', ...]

print(filters.describe("housing_types"))
```

Places resolve through `landwatch.places`. States, regions and counties come from
a bundled dataset and need no network; cities go through LandWatch's autocomplete
endpoint, because the site truncates its own per-state city facet at 300 entries.

```python
from landwatch import places

places.list_counties("tx")            # all 254, offline
places.resolve("Grayson County")      # -> matches in KY, TX and VA
places.resolve("Fredericksburg")      # a city: falls through to autocomplete
```

Refresh the bundled dataset with `python scripts/build_geography.py`.

## CLI

```bash
landwatch search --state texas --county grayson --price 200000-800000 --acres 5-50
landwatch search --state texas --region texoma \
    --type farms_and_ranches --type undeveloped \
    --price 100000-1000000 --acres 10-30 \
    --pages 3 --json results.json --csv results.csv
landwatch search --state colorado --geography mountain --geography off-grid --keyword cabin

landwatch url --state colorado --type hunting --acres 40-500   # print URL only
landwatch detail 422653962                                     # one listing, with price history
landwatch filters                                              # every filter dimension
landwatch filters geographies                                  # values of one filter
landwatch locations --state tx                                 # regions and counties in Texas
landwatch locations grayson                                    # resolve a place name
```

Ranges accept `MIN-MAX`, `MIN-` or `-MAX`, so `--price -50000` means "under $50,000".

Value names accept LandWatch's labels as well as the canonical slugs, so
`--housing-type cabin` and `--housing-type log-cabin` both work.

## Agent tool

```python
from landwatch.tools import build_langchain_tool

tool = build_langchain_tool()          # LangChain StructuredTool
```

```python
from landwatch.tools import build_crewai_tool

tool = build_crewai_tool()             # requires: pip install crewai
```

The tool accepts named strings (`property_types=["farms_and_ranches"]`) rather than the
internal integer bitmask, because models handle names far more reliably. Invalid
arguments come back as a JSON `error` field rather than an exception, so an agent can
read the message and retry.

## How the URL is built

LandWatch encodes every filter as a path segment in a fixed order:

```
/texas-land-for-sale/texoma-region/prop-types-3683/price-100000-1000000/acres-10-30/keyword-creek/page-2
 └ state            └ place        └ types         └ price               └ acreage   └ keyword     └ page
```

Segment reference (see [FILTERS.md](FILTERS.md) for every value):

| Filter | Segment | Notes |
| --- | --- | --- |
| State | `texas-land-for-sale` | Omit for a nationwide search, which uses `/land` |
| Region / county / city | `texoma-region`, `grayson-county`, `howe` | Slugs only; no ID lookup needed |
| Property types | `prop-types-3683` | Bitwise OR of the type flags |
| Ranges | `price-100000-1000000`, `acres-under-10`, `sqft-over-4001` | One-sided ranges use `under`/`over` |
| Minimums | `beds-over-3`, `baths-over-2` | |
| Activities | `fishing-activity` | 13 values |
| Geography | `geography-mountain`, `geography-off-grid` | Terrain, not location; 9 values |
| Land use | `present-use-homestead` | |
| Housing type | `housing-type-barndominium` | |
| HOA | `hoa-none`, `hoa-mandatory`, `hoa-voluntary` | |
| Availability | `available`, `under-contract`, `sold` | |
| Sale type | `for-sale`, `auctions` | |
| Keyword | `keyword-undeveloped` | Free text, slugified; sits after the ranges |
| Flags | `owner-financing`, `mineral-rights`, `video` | |
| Residence | `with-residence`, `no-residence` | |
| Page | `page-2` | 1-based; page 1 is implicit |

Property types are combined with **bitwise OR, not addition**. `WATERFRONT` (3584) is an
aggregate of `LAKEFRONT` (512), `OCEANFRONT` (1024) and `RIVERFRONT` (2048), so summing
the set `{3, 32, 64, 512, 1024, 2048, 3584}` yields 7267 whereas LandWatch expects 3683.

Note that LandWatch's `stateId` is the standard FIPS state code (Texas 48,
Colorado 8), so state ids never have to be looked up over the network.

`search(criteria, validate=True)` cross-checks the constructed URL against LandWatch's
own reading of it and logs a warning on any disagreement, which catches silent misreads
if the grammar changes.

## Transport requirements

Two details are load-bearing, and getting either wrong produces a blanket
`403 Access Denied`:

1. **HTTP/2 is mandatory.** The identical request over HTTP/1.1 is refused. This is why
   `httpx[http2]` is required and why `requests` cannot be used.
2. **The full browser header set is mandatory.** A `user-agent`-only request is refused;
   the `sec-ch-ua*`, `sec-fetch-*` and `priority` headers must all be present, along with
   a `referer` matching the corresponding public page.

The client sends one request per second by default and retries `403`/`429`/`5xx` with
exponential backoff.

## Structure

```
landwatch/
├── vocab.py     # Filter enums, property-type bitmask, slugify, state names and FIPS ids
├── filters.py   # FILTER_CATALOG: every filter, its segment and its values
├── FILTERS.md   # Generated filter reference
├── models.py    # SearchCriteria (input); Listing, SearchResult, PropertyDetail (output)
├── places.py    # State/region/county/city lookup, bundled plus autocomplete
├── data/        # geography.json: states, regions and counties
├── url.py       # Criteria -> URL path; pure and offline
├── client.py    # HTTP/2 transport, headers, retries, rate limiting
├── parse.py     # Raw JSON -> models, tolerant of schema drift
├── search.py    # search(), search_all(), collect(), get_detail()
├── cli.py       # Typer CLI
└── tools.py     # LangChain and CrewAI tool wrappers

scripts/
├── build_geography.py    # Regenerate data/geography.json (51 requests)
└── build_filters_doc.py  # Regenerate FILTERS.md from the catalog
```

## Tests

Tests run fully offline against fixtures captured from a real browsing session:

```bash
pytest tests/
```

`tests/test_filters.py` checks the catalog against LandWatch's own recorded facet
list, so a value the site adds, renames or re-numbers shows up as a failure the
next time the fixture is refreshed instead of as a quietly missing filter.

## Limitations

- These are LandWatch's internal, undocumented endpoints (versioned by a site id of
  `1113`) and can change without notice. Parsing degrades a renamed field to `None`
  rather than failing the whole search.
- `image_urls` are the same URLs LandWatch publishes in its own schema.org markup and
  load fine in a browser, but the asset host refuses non-browser clients, so the app
  cannot download the image bytes itself. Treat them as links to display.
- Page size is fixed at 25 by the backend and is not adjustable.
- City lists cannot be enumerated: LandWatch caps its own per-state city facet at
  300 entries, so cities are resolved by name through autocomplete rather than
  bundled. County lists are untruncated but cover only counties LandWatch has
  listings for, so a few sparse ones are missing (Texas has all 254; Kansas has
  103 of 105).
- `sort_order_id` is passed through as a raw integer. Neither recorded session
  opened the property sort dropdown, so the mapping from sort labels to ids is
  unknown.
- Review LandWatch's terms of service before any heavy or sustained use.
