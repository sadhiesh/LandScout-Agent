# LandWatch filter reference

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

## Where to search

### `state`

State to search. Accepts a name or two-letter abbreviation. Omit for a nationwide search. 51 values: the 50 states plus the District of Columbia.

- Kind: `place`
- URL segment: `<state>-land-for-sale`
- Note: Omitting this yields the national 'land' segment instead.

### `region` (LandWatch section: *Region*)

LandWatch's own multi-county region, e.g. 'texoma' or 'hill-country-north'. Regions are state-specific; Texas has 29. Requires state.

- Kind: `place`
- URL segment: `<region>-region`
- Note: Enumerate with landwatch.places.list_regions(state).

### `county` (LandWatch section: *County*)

County name without the word 'county', e.g. 'grayson'. Requires state. Covers the counties LandWatch indexes, which is most but not quite all of them.

- Kind: `place`
- URL segment: `<county>-county`
- Note: Enumerate with landwatch.places.list_counties(state).

### `city` (LandWatch section: *City*)

City name, e.g. 'howe'. Requires state.

- Kind: `place`
- URL segment: `<city>`
- Note: Cities are not bundled: LandWatch caps its own per-state city facet at 300 entries, so resolve them with landwatch.places.resolve().

## What kind of property

### `property_types` (LandWatch section: *Property Types*)

One or more property types, combined with bitwise OR into a single segment. Note that 'waterfront' is an aggregate of lakefront, oceanfront and riverfront.

- Kind: `bitmask`
- URL segment: `prop-types-<mask>`
- Note: The per-value segments listed here are LandWatch's readable single-type links; url.py emits the bitmask form, which is the only one able to express a combination.

| Value | LandWatch label | URL segment | Id |
| --- | --- | --- | --- |
| `farms_and_ranches` | Farms and Ranches | `farms-ranches` | 3 |
| `recreational` | Recreational | `recreational-property` | 4 |
| `timberland` | Timberland | `timberland-property` | 16 |
| `undeveloped` | Undeveloped | `undeveloped-land` | 32 |
| `commercial` | Commercial | `commercial-property` | 64 |
| `hunting` | Hunting | `hunting-property` | 128 |
| `horse` | Horse | `horse-property` | 256 |
| `lakefront` | Lakefront | `lakefront-property` | 512 |
| `oceanfront` | Oceanfront | `oceanfront-property` | 1024 |
| `riverfront` | Riverfront | `riverfront-property` | 2048 |
| `waterfront` | Waterfront | `waterfront-property` | 3584 |
| `homesite` | Homesite | `homesites` | 4096 |
| `house` | House | `homes` | 8192 |

### `geographies` (LandWatch section: *Geography*)

Terrain and setting of the land. Describes what the land is like, as opposed to the state/region/county/city filters that say where it is.

- Kind: `multi_enum`
- URL segment: `geography-<value>`

| Value | LandWatch label | URL segment | Id |
| --- | --- | --- | --- |
| `beachfront` | Beachfront | `geography-beachfront` | 1061 |
| `desert` | Desert | `geography-desert` | 1058 |
| `island` | Island | `geography-island` | 1060 |
| `lakefront` | Lakefront | `geography-lakefront` | 1057 |
| `mountain` | Mountain | `geography-mountain` | 1062 |
| `off-grid` | Off Grid | `geography-off-grid` | 1064 |
| `resort` | Resort | `geography-resort` | 1063 |
| `riverfront` | Riverfront | `geography-riverfront` | 1059 |
| `rural` | Rural | `geography-rural` | 1066 |

### `has_residence` (LandWatch section: *Residence*)

True requires a house on the land, False requires bare land, unset allows both.

- Kind: `tristate`
- URL segment: `with-residence | no-residence`

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `true` | Yes | `with-residence` |
| `false` | No | `no-residence` |

### `housing_types` (LandWatch section: *Housing Type*)

Type of structure on the property.

- Kind: `multi_enum`
- URL segment: `housing-type-<value>`

| Value | LandWatch label | URL segment | Id |
| --- | --- | --- | --- |
| `barndominium` | Barndominium | `housing-type-barndominium` | 1037 |
| `log-cabin` | Cabin | `housing-type-log-cabin` | 73 |
| `cottage` | Cottage | `housing-type-cottage` | 1047 |
| `guest-house` | Guest House | `housing-type-guest-house` | 1045 |
| `lake-house` | Lake House | `housing-type-lake-house` | 72 |
| `mobile-home` | Mobile Home | `housing-type-mobile-home` | 1044 |
| `tiny-home` | Tiny Home | `housing-type-tiny-home` | 1046 |

### `land_uses` (LandWatch section: *Land Uses*)

How the land is currently used.

- Kind: `multi_enum`
- URL segment: `present-use-<value>`

| Value | LandWatch label | URL segment | Id |
| --- | --- | --- | --- |
| `hobby-farm` | Hobby Farm | `present-use-hobby-farm` | 1051 |
| `homestead` | Homestead | `present-use-homestead` | 1070 |
| `orchard` | Orchard | `present-use-orchard` | 1050 |
| `pasture` | Pasture | `present-use-pasture` | 1097 |
| `poultry` | Poultry Farm | `present-use-poultry` | 755 |
| `vineyard` | Vineyard | `present-use-vineyard` | 1049 |

### `activities` (LandWatch section: *Activities*)

Recreational activities the property supports.

- Kind: `multi_enum`
- URL segment: `<value>-activity`

| Value | LandWatch label | URL segment | Id |
| --- | --- | --- | --- |
| `aquatic-sporting` | Aquatic Sporting | `aquatic-sporting-activity` | 1053 |
| `aviation` | Aviation | `aviation-activity` | 1009 |
| `beach` | Beach | `beach-activity` | 1010 |
| `boating` | Boating | `boating-activity` | 1011 |
| `camping` | Camping | `camping-activity` | 1012 |
| `canoeing-kayaking` | Canoeing/Kayaking | `canoeing-kayaking-activity` | 1013 |
| `conservation` | Conservation | `conservation-activity` | 1014 |
| `fishing` | Fishing | `fishing-activity` | 1015 |
| `golfing` | Golfing | `golfing-activity` | 1052 |
| `horseback-riding` | Horseback Riding | `horseback-riding-activity` | 1016 |
| `off-roading` | Off-roading | `off-roading-activity` | 1018 |
| `rving` | RVing | `rving-activity` | 1019 |
| `skiing` | Skiing | `skiing-activity` | 1065 |

## Price and size

### `price` (LandWatch section: *Price*)

Price in US dollars, set via price_min and price_max.

- Kind: `range`
- URL segment: `price-<min>-<max> | price-under-<max> | price-over-<min>`
- Any value is accepted; the table lists LandWatch's own buckets.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `under-49999` | $0 - $49,999 | `price-under-49999` |
| `50000-99999` | $50,000 - $99,999 | `price-50000-99999` |
| `100000-249999` | $100,000 - $249,999 | `price-100000-249999` |
| `250000-499999` | $250,000 - $499,999 | `price-250000-499999` |
| `500000-749999` | $500,000 - $749,999 | `price-500000-749999` |
| `750000-999999` | $750,000 - $999,999 | `price-750000-999999` |
| `over-1000000` | $1,000,000 and up | `price-over-1000000` |

### `acres` (LandWatch section: *Parcel Size*)

Parcel size in acres, set via acres_min and acres_max.

- Kind: `range`
- URL segment: `acres-<min>-<max> | acres-under-<max> | acres-over-<min>`
- Any value is accepted; the table lists LandWatch's own buckets.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `under-10` | 0 - 10 Acres | `acres-under-10` |
| `11-50` | 11 - 50 Acres | `acres-11-50` |
| `51-100` | 51 - 100 Acres | `acres-51-100` |
| `101-200` | 101 - 200 Acres | `acres-101-200` |
| `201-500` | 201 - 500 Acres | `acres-201-500` |
| `over-500` | 500+ Acres | `acres-over-500` |
| `over-1000` | 1,000+ Acres | `acres-over-1000` |

### `sqft` (LandWatch section: *Square Feet*)

Home square footage, set via sqft_min and sqft_max.

- Kind: `range`
- URL segment: `sqft-<min>-<max> | sqft-under-<max> | sqft-over-<min>`
- Any value is accepted; the table lists LandWatch's own buckets.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `under-500` | 0 - 500 Sq. Ft. | `sqft-under-500` |
| `501-1000` | 501 - 1,000 Sq. Ft. | `sqft-501-1000` |
| `1001-2000` | 1,001 - 2,000 Sq. Ft. | `sqft-1001-2000` |
| `2001-3000` | 2,001 - 3,000 Sq. Ft. | `sqft-2001-3000` |
| `3001-4000` | 3,001 - 4,000 Sq. Ft. | `sqft-3001-4000` |
| `over-4001` | 4,001+ Sq. Ft. | `sqft-over-4001` |

### `beds_min` (LandWatch section: *Bedrooms*)

Minimum bedroom count.

- Kind: `minimum`
- URL segment: `beds-over-<min>`
- Any value is accepted; the table lists LandWatch's own buckets.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `over-1` | 1+ Bedrooms | `beds-over-1` |
| `over-2` | 2+ Bedrooms | `beds-over-2` |
| `over-3` | 3+ Bedrooms | `beds-over-3` |
| `over-4` | 4+ Bedrooms | `beds-over-4` |

### `baths_min` (LandWatch section: *Bathrooms*)

Minimum bathroom count.

- Kind: `minimum`
- URL segment: `baths-over-<min>`
- Any value is accepted; the table lists LandWatch's own buckets.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `over-1` | 1+ Bathrooms | `baths-over-1` |
| `over-2` | 2+ Bathrooms | `baths-over-2` |
| `over-3` | 3+ Bathrooms | `baths-over-3` |
| `over-4` | 4+ Bathrooms | `baths-over-4` |

## Listing status

### `market_statuses` (LandWatch section: *Availability*)

Listing availability. Defaults to available plus under contract, matching the site.

- Kind: `multi_enum`
- URL segment: `<value>`
- Note: off-market and sold only take effect alongside available and under-contract, which is how LandWatch's own links behave.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `available` | Available | `available` |
| `under-contract` | Under Contract | `under-contract` |
| `off-market` | Off Market | `off-market` |
| `sold` | Sold | `sold` |

### `sale_type` (LandWatch section: *Sale Type*)

Restrict to conventional listings or to auctions.

- Kind: `single_enum`
- URL segment: `<value>`

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `for-sale` | For Sale | `for-sale` |
| `auctions` | Auction | `auctions` |

### `price_reduction_days`

Only listings whose price dropped within the last N days.

- Kind: `minimum`
- URL segment: `price-reduction-<days>-days`
- Any value is accepted; the table lists LandWatch's own buckets.

| Value | LandWatch label | URL segment |
| --- | --- | --- |
| `30` | Last 30 days | `price-reduction-30-days` |
| `60` | Last 60 days | `price-reduction-60-days` |
| `90` | Last 90 days | `price-reduction-90-days` |

### `hoa` (LandWatch section: *HOA*)

Homeowners association requirement.

- Kind: `single_enum`
- URL segment: `<value>`

| Value | LandWatch label | URL segment | Id |
| --- | --- | --- | --- |
| `hoa-mandatory` | Yes (Mandatory) | `hoa-mandatory` | 43 |
| `hoa-none` | No | `hoa-none` | 44 |
| `hoa-voluntary` | Yes (Voluntary) | `hoa-voluntary` | 45 |

## Free text

### `keyword`

Free-text search across listing titles and descriptions, e.g. 'undeveloped' or 'creek frontage'. Slugified into the segment.

- Kind: `text`
- URL segment: `keyword-<text>`
- Note: Rendered after the range segments, matching LandWatch's own URLs.

## Flags

### `owner_financing` (LandWatch section: *Misc*)

Only listings flagged 'Owner Financing'.

- Kind: `boolean`
- URL segment: `owner-financing`

### `mineral_rights` (LandWatch section: *Misc*)

Only listings flagged 'Mineral Rights'.

- Kind: `boolean`
- URL segment: `mineral-rights`

### `virtual_tour` (LandWatch section: *Misc*)

Only listings flagged 'Virtual Tour'.

- Kind: `boolean`
- URL segment: `virtual-tour`

### `exterior_tour` (LandWatch section: *Misc*)

Only listings flagged 'Exterior Tour'.

- Kind: `boolean`
- URL segment: `exterior-tour`

### `has_video` (LandWatch section: *Misc*)

Only listings flagged 'Property Video'.

- Kind: `boolean`
- URL segment: `video`

### `custom_map` (LandWatch section: *Misc*)

Only listings flagged 'Custom Map'.

- Kind: `boolean`
- URL segment: `custom-map`

## Paging and sorting

### `page`

1-based result page. 25 listings per page, fixed by the backend.

- Kind: `minimum`
- URL segment: `page-<n>`

### `sort_order_id`

LandWatch's sort order, passed through as a raw integer. 0 is the default relevance sort.

- Kind: `opaque`
- URL segment: `(not a path segment)`
- Note: The label-to-id mapping is not known: neither recorded session opened the property sort dropdown. Value 26 was observed in a live payload.
