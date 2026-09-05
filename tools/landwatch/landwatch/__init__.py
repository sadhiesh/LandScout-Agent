"""LandWatch land-listing search client.

Turns structured land-buying criteria into a LandWatch search URL, fetches the
matching listings, and returns them as typed models.

``filters.FILTER_CATALOG`` documents every filter LandWatch accepts and its
possible values; :mod:`landwatch.places` resolves the states, regions, counties
and cities those filters can name.
"""

from . import filters, places
from .client import BlockedError, LandWatchClient, LandWatchError, LocationNotFound
from .filters import FILTER_CATALOG, FilterKind, FilterSpec, FilterValue
from .models import (
    Broker,
    Listing,
    PriceEvent,
    PropertyDetail,
    SearchCriteria,
    SearchResult,
)
from .places import Place, PlaceKind
from .search import collect, get_detail, search, search_all
from .url import build_path, build_url
from .vocab import (
    Activity,
    Geography,
    Hoa,
    HousingType,
    LandUse,
    MarketStatus,
    PropertyType,
    SaleType,
)

__version__ = "0.2.0"

__all__ = [
    "FILTER_CATALOG",
    "Activity",
    "BlockedError",
    "Broker",
    "FilterKind",
    "FilterSpec",
    "FilterValue",
    "Geography",
    "Hoa",
    "HousingType",
    "LandUse",
    "LandWatchClient",
    "LandWatchError",
    "Listing",
    "LocationNotFound",
    "MarketStatus",
    "Place",
    "PlaceKind",
    "PriceEvent",
    "PropertyDetail",
    "PropertyType",
    "SaleType",
    "SearchCriteria",
    "SearchResult",
    "build_path",
    "build_url",
    "collect",
    "filters",
    "get_detail",
    "places",
    "search",
    "search_all",
]
