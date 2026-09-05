"""Filter vocabulary for LandWatch search URLs.

Every identifier and URL segment here was decoded from a recorded browsing
session (HAR) and verified against the live endpoints. See ``url.py`` for how
the segments are assembled.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum, IntFlag

SITE_ID = 1113
BASE_URL = "https://www.landwatch.com"

# Page size is fixed by the backend; it is not a request parameter.
RESULTS_PER_PAGE = 25


class PropertyType(IntFlag):
    """Property type filter, encoded into the URL as a bitwise OR.

    WATERFRONT is an aggregate of LAKEFRONT|OCEANFRONT|RIVERFRONT, which is why
    these must be combined with OR rather than summed: LandWatch encodes the set
    {3, 32, 64, 512, 1024, 2048, 3584} as 3683, not as their sum of 7267.
    """

    FARMS_AND_RANCHES = 3
    RECREATIONAL = 4
    TIMBERLAND = 16
    UNDEVELOPED = 32
    COMMERCIAL = 64
    HUNTING = 128
    HORSE = 256
    LAKEFRONT = 512
    OCEANFRONT = 1024
    RIVERFRONT = 2048
    WATERFRONT = 3584
    HOMESITE = 4096
    HOUSE = 8192


# LandWatch publishes a readable slug per property type alongside the numeric
# bitmask, e.g. /texas-land-for-sale/timberland-property. Either form resolves,
# but only the bitmask can express a combination, so url.py always emits
# prop-types-<mask> and these slugs exist for building canonical single-type
# links and for documentation.
PROPERTY_TYPE_SLUGS: dict[PropertyType, str] = {
    PropertyType.FARMS_AND_RANCHES: "farms-ranches",
    PropertyType.RECREATIONAL: "recreational-property",
    PropertyType.TIMBERLAND: "timberland-property",
    PropertyType.UNDEVELOPED: "undeveloped-land",
    PropertyType.COMMERCIAL: "commercial-property",
    PropertyType.HUNTING: "hunting-property",
    PropertyType.HORSE: "horse-property",
    PropertyType.LAKEFRONT: "lakefront-property",
    PropertyType.OCEANFRONT: "oceanfront-property",
    PropertyType.RIVERFRONT: "riverfront-property",
    PropertyType.WATERFRONT: "waterfront-property",
    PropertyType.HOMESITE: "homesites",
    PropertyType.HOUSE: "homes",
}


class MarketStatus(str, Enum):
    AVAILABLE = "available"
    UNDER_CONTRACT = "under-contract"
    OFF_MARKET = "off-market"
    SOLD = "sold"


class SaleType(str, Enum):
    """Whether to restrict to conventional sales or auctions."""

    FOR_SALE = "for-sale"
    AUCTION = "auctions"


class Activity(str, Enum):
    """Recreational activity filters, rendered as ``<value>-activity``."""

    AQUATIC_SPORTING = "aquatic-sporting"
    AVIATION = "aviation"
    BEACH = "beach"
    BOATING = "boating"
    CAMPING = "camping"
    CANOEING_KAYAKING = "canoeing-kayaking"
    CONSERVATION = "conservation"
    FISHING = "fishing"
    GOLFING = "golfing"
    HORSEBACK_RIDING = "horseback-riding"
    OFF_ROADING = "off-roading"
    RVING = "rving"
    SKIING = "skiing"


class Geography(str, Enum):
    """Terrain and setting filters, rendered as ``geography-<value>``.

    Distinct from the place filters (state/region/county/city): these describe
    what the land is like rather than where it is.
    """

    BEACHFRONT = "beachfront"
    DESERT = "desert"
    ISLAND = "island"
    LAKEFRONT = "lakefront"
    MOUNTAIN = "mountain"
    OFF_GRID = "off-grid"
    RESORT = "resort"
    RIVERFRONT = "riverfront"
    RURAL = "rural"


class LandUse(str, Enum):
    """Present-use filters, rendered as ``present-use-<value>``."""

    HOBBY_FARM = "hobby-farm"
    HOMESTEAD = "homestead"
    ORCHARD = "orchard"
    PASTURE = "pasture"
    POULTRY = "poultry"
    VINEYARD = "vineyard"


class HousingType(str, Enum):
    """Structure filters, rendered as ``housing-type-<value>``."""

    BARNDOMINIUM = "barndominium"
    # LandWatch labels this one "Cabin" but slugs it "log-cabin".
    CABIN = "log-cabin"
    COTTAGE = "cottage"
    GUEST_HOUSE = "guest-house"
    LAKE_HOUSE = "lake-house"
    MOBILE_HOME = "mobile-home"
    TINY_HOME = "tiny-home"


class Hoa(str, Enum):
    NONE = "hoa-none"
    MANDATORY = "hoa-mandatory"
    VOLUNTARY = "hoa-voluntary"


# Standalone boolean segments, mapped from SearchCriteria field name to segment.
BOOLEAN_SEGMENTS: dict[str, str] = {
    "owner_financing": "owner-financing",
    "mineral_rights": "mineral-rights",
    "virtual_tour": "virtual-tour",
    "exterior_tour": "exterior-tour",
    "has_video": "video",
    "custom_map": "custom-map",
}

# Property-type ids as they appear on individual listings (``typeIds``). These
# are plain ids rather than the bitmask used in URLs, so a listing tagged
# [1, 2, 128] means Farms and Ranches (1|2) plus Hunting.
LISTING_TYPE_LABELS: dict[int, str] = {
    1: "Farms and Ranches",
    2: "Farms and Ranches",
    4: "Recreational",
    16: "Timberland",
    32: "Undeveloped",
    64: "Commercial",
    128: "Hunting",
    256: "Horse",
    512: "Lakefront",
    1024: "Oceanfront",
    2048: "Riverfront",
    4096: "Homesite",
    8192: "House",
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Convert a human place name into a LandWatch URL slug.

    ``"St. Mary's County"`` becomes ``"st-marys-county"``, matching the slugs
    LandWatch publishes in its own filter links.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    # Drop apostrophes before splitting so "mary's" collapses to "marys".
    ascii_only = ascii_only.replace("'", "")
    return _SLUG_STRIP.sub("-", ascii_only).strip("-")


def state_segment(state: str) -> str:
    """Build the leading state segment, e.g. ``texas-land-for-sale``.

    Accepts a state name or a two-letter abbreviation.
    """
    key = state.strip().lower()
    name = STATE_ABBREVIATIONS.get(key, key)
    return f"{slugify(name)}-land-for-sale"


STATE_ABBREVIATIONS: dict[str, str] = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "dc": "district-of-columbia",
    "de": "delaware",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new-hampshire",
    "nj": "new-jersey",
    "nm": "new-mexico",
    "ny": "new-york",
    "nc": "north-carolina",
    "nd": "north-dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode-island",
    "sc": "south-carolina",
    "sd": "south-dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west-virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
}

# LandWatch's ``stateId`` is the standard FIPS state code, confirmed against the
# location autocomplete endpoint (Texas 48, Colorado 8, Alabama 1, Illinois 17).
# That means state ids never have to be looked up over the network.
STATE_FIPS: dict[str, int] = {
    "al": 1,
    "ak": 2,
    "az": 4,
    "ar": 5,
    "ca": 6,
    "co": 8,
    "ct": 9,
    "de": 10,
    "dc": 11,
    "fl": 12,
    "ga": 13,
    "hi": 15,
    "id": 16,
    "il": 17,
    "in": 18,
    "ia": 19,
    "ks": 20,
    "ky": 21,
    "la": 22,
    "me": 23,
    "md": 24,
    "ma": 25,
    "mi": 26,
    "mn": 27,
    "ms": 28,
    "mo": 29,
    "mt": 30,
    "ne": 31,
    "nv": 32,
    "nh": 33,
    "nj": 34,
    "nm": 35,
    "ny": 36,
    "nc": 37,
    "nd": 38,
    "oh": 39,
    "ok": 40,
    "or": 41,
    "pa": 42,
    "ri": 44,
    "sc": 45,
    "sd": 46,
    "tn": 47,
    "tx": 48,
    "ut": 49,
    "vt": 50,
    "va": 51,
    "wa": 53,
    "wv": 54,
    "wi": 55,
    "wy": 56,
}

# Slug to abbreviation, the reverse of STATE_ABBREVIATIONS. The 51 slugs match
# exactly the set LandWatch links from its homepage.
STATE_SLUG_TO_ABBREVIATION: dict[str, str] = {
    slug: abbreviation for abbreviation, slug in STATE_ABBREVIATIONS.items()
}
