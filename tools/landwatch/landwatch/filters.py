"""The complete dictionary of LandWatch search filters and their values.

``FILTER_CATALOG`` describes every filter dimension LandWatch exposes: what it is
called on the site, which :class:`~landwatch.models.SearchCriteria` field drives
it, how it renders into the URL path, and the full set of accepted values with
LandWatch's own internal id and display label.

The catalog is the single source of truth for the CLI's ``filters`` command, the
agent tool descriptions and ``FILTERS.md``, so those three can never drift from
each other. Values were transcribed from the ``filterSections`` array of a
state-level search response, which is LandWatch's own enumeration of its facets;
``tests/test_filters.py`` re-checks the catalog against that recorded payload.

Ids are included because LandWatch's ``/api/property/searchUrl`` endpoint accepts
them, but note that url.py needs only the segments, so the ids are informational
for most callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from .vocab import (
    PROPERTY_TYPE_SLUGS,
    Activity,
    Geography,
    Hoa,
    HousingType,
    LandUse,
    MarketStatus,
    PropertyType,
    SaleType,
)


class FilterKind(str, Enum):
    """How a filter dimension behaves, which determines how it is supplied."""

    BITMASK = "bitmask"
    """A set of flags combined with bitwise OR into one segment."""

    MULTI_ENUM = "multi_enum"
    """Zero or more named values, each rendering its own segment."""

    SINGLE_ENUM = "single_enum"
    """At most one named value."""

    RANGE = "range"
    """A numeric min and/or max. Any value is accepted, not just the presets."""

    MINIMUM = "minimum"
    """A single numeric lower bound."""

    BOOLEAN = "boolean"
    """A flag that either adds its segment or does not."""

    TRISTATE = "tristate"
    """True, False and unset each mean something different."""

    TEXT = "text"
    """Free text, slugified into the segment."""

    PLACE = "place"
    """A geographic name whose valid values are too numerous to enumerate here.

    Use :mod:`landwatch.places` to discover and validate these.
    """

    OPAQUE = "opaque"
    """A value LandWatch accepts but whose vocabulary could not be decoded."""


@dataclass(frozen=True)
class FilterValue:
    """One accepted value of a filter dimension."""

    value: str
    """What to pass in ``SearchCriteria``."""

    label: str
    """LandWatch's own display text for this value."""

    segment: str
    """The URL path segment this value produces."""

    id: int | None = None
    """LandWatch's internal id, where the site exposes one."""


@dataclass(frozen=True)
class FilterSpec:
    """One filter dimension: what it accepts and how it reaches the URL."""

    name: str
    """The ``SearchCriteria`` field name."""

    section: str | None
    """The heading LandWatch files this filter under, or None if it has no facet UI."""

    kind: FilterKind
    description: str
    segment: str
    """The segment format, with ``<>`` placeholders."""

    values: tuple[FilterValue, ...] = ()
    """Every accepted value, for the enumerable kinds."""

    presets: tuple[FilterValue, ...] = ()
    """LandWatch's own suggested buckets, for RANGE and MINIMUM kinds.

    These are shortcuts the site offers, not a restriction: arbitrary bounds work.
    """

    notes: str | None = None

    @property
    def value_names(self) -> list[str]:
        return [v.value for v in self.values]


def _enum_values(
    entries: tuple[tuple[Enum, int | None, str], ...],
    segment: str,
) -> tuple[FilterValue, ...]:
    """Build filter values from enum members plus LandWatch's ids and labels.

    Deriving the value set from the enum rather than restating it keeps the
    catalog and the enums from disagreeing.
    """
    return tuple(
        FilterValue(
            value=str(member.value),
            label=label,
            segment=segment.replace("<value>", str(member.value)),
            id=identifier,
        )
        for member, identifier, label in entries
    )


PROPERTY_TYPE_VALUES: tuple[FilterValue, ...] = tuple(
    FilterValue(
        value=member.name.lower(),
        label=label,
        segment=PROPERTY_TYPE_SLUGS[member],
        id=int(member),
    )
    for member, label in (
        (PropertyType.FARMS_AND_RANCHES, "Farms and Ranches"),
        (PropertyType.RECREATIONAL, "Recreational"),
        (PropertyType.TIMBERLAND, "Timberland"),
        (PropertyType.UNDEVELOPED, "Undeveloped"),
        (PropertyType.COMMERCIAL, "Commercial"),
        (PropertyType.HUNTING, "Hunting"),
        (PropertyType.HORSE, "Horse"),
        (PropertyType.LAKEFRONT, "Lakefront"),
        (PropertyType.OCEANFRONT, "Oceanfront"),
        (PropertyType.RIVERFRONT, "Riverfront"),
        (PropertyType.WATERFRONT, "Waterfront"),
        (PropertyType.HOMESITE, "Homesite"),
        (PropertyType.HOUSE, "House"),
    )
)

ACTIVITY_VALUES = _enum_values(
    (
        (Activity.AQUATIC_SPORTING, 1053, "Aquatic Sporting"),
        (Activity.AVIATION, 1009, "Aviation"),
        (Activity.BEACH, 1010, "Beach"),
        (Activity.BOATING, 1011, "Boating"),
        (Activity.CAMPING, 1012, "Camping"),
        (Activity.CANOEING_KAYAKING, 1013, "Canoeing/Kayaking"),
        (Activity.CONSERVATION, 1014, "Conservation"),
        (Activity.FISHING, 1015, "Fishing"),
        (Activity.GOLFING, 1052, "Golfing"),
        (Activity.HORSEBACK_RIDING, 1016, "Horseback Riding"),
        (Activity.OFF_ROADING, 1018, "Off-roading"),
        (Activity.RVING, 1019, "RVing"),
        (Activity.SKIING, 1065, "Skiing"),
    ),
    "<value>-activity",
)

GEOGRAPHY_VALUES = _enum_values(
    (
        (Geography.BEACHFRONT, 1061, "Beachfront"),
        (Geography.DESERT, 1058, "Desert"),
        (Geography.ISLAND, 1060, "Island"),
        (Geography.LAKEFRONT, 1057, "Lakefront"),
        (Geography.MOUNTAIN, 1062, "Mountain"),
        (Geography.OFF_GRID, 1064, "Off Grid"),
        (Geography.RESORT, 1063, "Resort"),
        (Geography.RIVERFRONT, 1059, "Riverfront"),
        (Geography.RURAL, 1066, "Rural"),
    ),
    "geography-<value>",
)

LAND_USE_VALUES = _enum_values(
    (
        (LandUse.HOBBY_FARM, 1051, "Hobby Farm"),
        (LandUse.HOMESTEAD, 1070, "Homestead"),
        (LandUse.ORCHARD, 1050, "Orchard"),
        (LandUse.PASTURE, 1097, "Pasture"),
        (LandUse.POULTRY, 755, "Poultry Farm"),
        (LandUse.VINEYARD, 1049, "Vineyard"),
    ),
    "present-use-<value>",
)

HOUSING_TYPE_VALUES = _enum_values(
    (
        (HousingType.BARNDOMINIUM, 1037, "Barndominium"),
        (HousingType.CABIN, 73, "Cabin"),
        (HousingType.COTTAGE, 1047, "Cottage"),
        (HousingType.GUEST_HOUSE, 1045, "Guest House"),
        (HousingType.LAKE_HOUSE, 72, "Lake House"),
        (HousingType.MOBILE_HOME, 1044, "Mobile Home"),
        (HousingType.TINY_HOME, 1046, "Tiny Home"),
    ),
    "housing-type-<value>",
)

HOA_VALUES: tuple[FilterValue, ...] = tuple(
    FilterValue(value=member.value, label=label, segment=member.value, id=identifier)
    for member, identifier, label in (
        (Hoa.MANDATORY, 43, "Yes (Mandatory)"),
        (Hoa.NONE, 44, "No"),
        (Hoa.VOLUNTARY, 45, "Yes (Voluntary)"),
    )
)

MARKET_STATUS_VALUES: tuple[FilterValue, ...] = tuple(
    FilterValue(value=member.value, label=label, segment=member.value)
    for member, label in (
        (MarketStatus.AVAILABLE, "Available"),
        (MarketStatus.UNDER_CONTRACT, "Under Contract"),
        (MarketStatus.OFF_MARKET, "Off Market"),
        (MarketStatus.SOLD, "Sold"),
    )
)

SALE_TYPE_VALUES: tuple[FilterValue, ...] = tuple(
    FilterValue(value=member.value, label=label, segment=member.value)
    for member, label in ((SaleType.FOR_SALE, "For Sale"), (SaleType.AUCTION, "Auction"))
)


def _presets(prefix: str, buckets: tuple[tuple[str, str], ...]) -> tuple[FilterValue, ...]:
    return tuple(
        FilterValue(value=segment.removeprefix(f"{prefix}-"), label=label, segment=segment)
        for label, segment in buckets
    )


PRICE_PRESETS = _presets(
    "price",
    (
        ("$0 - $49,999", "price-under-49999"),
        ("$50,000 - $99,999", "price-50000-99999"),
        ("$100,000 - $249,999", "price-100000-249999"),
        ("$250,000 - $499,999", "price-250000-499999"),
        ("$500,000 - $749,999", "price-500000-749999"),
        ("$750,000 - $999,999", "price-750000-999999"),
        ("$1,000,000 and up", "price-over-1000000"),
    ),
)

ACRES_PRESETS = _presets(
    "acres",
    (
        ("0 - 10 Acres", "acres-under-10"),
        ("11 - 50 Acres", "acres-11-50"),
        ("51 - 100 Acres", "acres-51-100"),
        ("101 - 200 Acres", "acres-101-200"),
        ("201 - 500 Acres", "acres-201-500"),
        ("500+ Acres", "acres-over-500"),
        ("1,000+ Acres", "acres-over-1000"),
    ),
)

SQFT_PRESETS = _presets(
    "sqft",
    (
        ("0 - 500 Sq. Ft.", "sqft-under-500"),
        ("501 - 1,000 Sq. Ft.", "sqft-501-1000"),
        ("1,001 - 2,000 Sq. Ft.", "sqft-1001-2000"),
        ("2,001 - 3,000 Sq. Ft.", "sqft-2001-3000"),
        ("3,001 - 4,000 Sq. Ft.", "sqft-3001-4000"),
        ("4,001+ Sq. Ft.", "sqft-over-4001"),
    ),
)

BEDS_PRESETS = _presets(
    "beds",
    (
        ("1+ Bedrooms", "beds-over-1"),
        ("2+ Bedrooms", "beds-over-2"),
        ("3+ Bedrooms", "beds-over-3"),
        ("4+ Bedrooms", "beds-over-4"),
    ),
)

BATHS_PRESETS = _presets(
    "baths",
    (
        ("1+ Bathrooms", "baths-over-1"),
        ("2+ Bathrooms", "baths-over-2"),
        ("3+ Bathrooms", "baths-over-3"),
        ("4+ Bathrooms", "baths-over-4"),
    ),
)

RESIDENCE_VALUES: tuple[FilterValue, ...] = (
    FilterValue(value="true", label="Yes", segment="with-residence"),
    FilterValue(value="false", label="No", segment="no-residence"),
)

MISC_BOOLEANS: tuple[tuple[str, str, str], ...] = (
    ("owner_financing", "Owner Financing", "owner-financing"),
    ("mineral_rights", "Mineral Rights", "mineral-rights"),
    ("virtual_tour", "Virtual Tour", "virtual-tour"),
    ("exterior_tour", "Exterior Tour", "exterior-tour"),
    ("has_video", "Property Video", "video"),
    ("custom_map", "Custom Map", "custom-map"),
)


def _specs() -> dict[str, FilterSpec]:
    specs: list[FilterSpec] = [
        FilterSpec(
            name="state",
            section=None,
            kind=FilterKind.PLACE,
            description=(
                "State to search. Accepts a name or two-letter abbreviation. "
                "Omit for a nationwide search. 51 values: the 50 states plus "
                "the District of Columbia."
            ),
            segment="<state>-land-for-sale",
            notes="Omitting this yields the national 'land' segment instead.",
        ),
        FilterSpec(
            name="region",
            section="Region",
            kind=FilterKind.PLACE,
            description=(
                "LandWatch's own multi-county region, e.g. 'texoma' or 'hill-country-north'. "
                "Regions are state-specific; Texas has 29. Requires state."
            ),
            segment="<region>-region",
            notes="Enumerate with landwatch.places.list_regions(state).",
        ),
        FilterSpec(
            name="county",
            section="County",
            kind=FilterKind.PLACE,
            description=(
                "County name without the word 'county', e.g. 'grayson'. Requires state. "
                "Covers the counties LandWatch indexes, which is most but not "
                "quite all of them."
            ),
            segment="<county>-county",
            notes="Enumerate with landwatch.places.list_counties(state).",
        ),
        FilterSpec(
            name="city",
            section="City",
            kind=FilterKind.PLACE,
            description="City name, e.g. 'howe'. Requires state.",
            segment="<city>",
            notes=(
                "Cities are not bundled: LandWatch caps its own per-state city facet at "
                "300 entries, so resolve them with landwatch.places.resolve()."
            ),
        ),
        FilterSpec(
            name="property_types",
            section="Property Types",
            kind=FilterKind.BITMASK,
            description=(
                "One or more property types, combined with bitwise OR into a single "
                "segment. Note that 'waterfront' is an aggregate of lakefront, "
                "oceanfront and riverfront."
            ),
            segment="prop-types-<mask>",
            values=PROPERTY_TYPE_VALUES,
            notes=(
                "The per-value segments listed here are LandWatch's readable "
                "single-type links; url.py emits the bitmask form, which is the only "
                "one able to express a combination."
            ),
        ),
        FilterSpec(
            name="market_statuses",
            section="Availability",
            kind=FilterKind.MULTI_ENUM,
            description=(
                "Listing availability. Defaults to available plus under contract, "
                "matching the site."
            ),
            segment="<value>",
            values=MARKET_STATUS_VALUES,
            notes=(
                "off-market and sold only take effect alongside available and "
                "under-contract, which is how LandWatch's own links behave."
            ),
        ),
        FilterSpec(
            name="sale_type",
            section="Sale Type",
            kind=FilterKind.SINGLE_ENUM,
            description="Restrict to conventional listings or to auctions.",
            segment="<value>",
            values=SALE_TYPE_VALUES,
        ),
        FilterSpec(
            name="has_residence",
            section="Residence",
            kind=FilterKind.TRISTATE,
            description=(
                "True requires a house on the land, False requires bare land, "
                "unset allows both."
            ),
            segment="with-residence | no-residence",
            values=RESIDENCE_VALUES,
        ),
        FilterSpec(
            name="activities",
            section="Activities",
            kind=FilterKind.MULTI_ENUM,
            description="Recreational activities the property supports.",
            segment="<value>-activity",
            values=ACTIVITY_VALUES,
        ),
        FilterSpec(
            name="geographies",
            section="Geography",
            kind=FilterKind.MULTI_ENUM,
            description=(
                "Terrain and setting of the land. Describes what the land is like, "
                "as opposed to the state/region/county/city filters that say where it is."
            ),
            segment="geography-<value>",
            values=GEOGRAPHY_VALUES,
        ),
        FilterSpec(
            name="land_uses",
            section="Land Uses",
            kind=FilterKind.MULTI_ENUM,
            description="How the land is currently used.",
            segment="present-use-<value>",
            values=LAND_USE_VALUES,
        ),
        FilterSpec(
            name="housing_types",
            section="Housing Type",
            kind=FilterKind.MULTI_ENUM,
            description="Type of structure on the property.",
            segment="housing-type-<value>",
            values=HOUSING_TYPE_VALUES,
        ),
        FilterSpec(
            name="hoa",
            section="HOA",
            kind=FilterKind.SINGLE_ENUM,
            description="Homeowners association requirement.",
            segment="<value>",
            values=HOA_VALUES,
        ),
        FilterSpec(
            name="price",
            section="Price",
            kind=FilterKind.RANGE,
            description="Price in US dollars, set via price_min and price_max.",
            segment="price-<min>-<max> | price-under-<max> | price-over-<min>",
            presets=PRICE_PRESETS,
        ),
        FilterSpec(
            name="acres",
            section="Parcel Size",
            kind=FilterKind.RANGE,
            description="Parcel size in acres, set via acres_min and acres_max.",
            segment="acres-<min>-<max> | acres-under-<max> | acres-over-<min>",
            presets=ACRES_PRESETS,
        ),
        FilterSpec(
            name="sqft",
            section="Square Feet",
            kind=FilterKind.RANGE,
            description="Home square footage, set via sqft_min and sqft_max.",
            segment="sqft-<min>-<max> | sqft-under-<max> | sqft-over-<min>",
            presets=SQFT_PRESETS,
        ),
        FilterSpec(
            name="beds_min",
            section="Bedrooms",
            kind=FilterKind.MINIMUM,
            description="Minimum bedroom count.",
            segment="beds-over-<min>",
            presets=BEDS_PRESETS,
        ),
        FilterSpec(
            name="baths_min",
            section="Bathrooms",
            kind=FilterKind.MINIMUM,
            description="Minimum bathroom count.",
            segment="baths-over-<min>",
            presets=BATHS_PRESETS,
        ),
        FilterSpec(
            name="keyword",
            section=None,
            kind=FilterKind.TEXT,
            description=(
                "Free-text search across listing titles and descriptions, "
                "e.g. 'undeveloped' or 'creek frontage'. Slugified into the segment."
            ),
            segment="keyword-<text>",
            notes="Rendered after the range segments, matching LandWatch's own URLs.",
        ),
        FilterSpec(
            name="price_reduction_days",
            section=None,
            kind=FilterKind.MINIMUM,
            description="Only listings whose price dropped within the last N days.",
            segment="price-reduction-<days>-days",
            presets=(
                FilterValue(value="30", label="Last 30 days", segment="price-reduction-30-days"),
                FilterValue(value="60", label="Last 60 days", segment="price-reduction-60-days"),
                FilterValue(value="90", label="Last 90 days", segment="price-reduction-90-days"),
            ),
        ),
        FilterSpec(
            name="sort_order_id",
            section=None,
            kind=FilterKind.OPAQUE,
            description=(
                "LandWatch's sort order, passed through as a raw integer. 0 is the "
                "default relevance sort."
            ),
            segment="(not a path segment)",
            notes=(
                "The label-to-id mapping is not known: neither recorded session opened "
                "the property sort dropdown. Value 26 was observed in a live payload."
            ),
        ),
        FilterSpec(
            name="page",
            section=None,
            kind=FilterKind.MINIMUM,
            description="1-based result page. 25 listings per page, fixed by the backend.",
            segment="page-<n>",
        ),
    ]

    specs.extend(
        FilterSpec(
            name=name,
            section="Misc",
            kind=FilterKind.BOOLEAN,
            description=f"Only listings flagged '{label}'.",
            segment=segment,
            values=(FilterValue(value="true", label=label, segment=segment),),
        )
        for name, label, segment in MISC_BOOLEANS
    )

    return {spec.name: spec for spec in specs}


FILTER_CATALOG: dict[str, FilterSpec] = _specs()
"""Every LandWatch filter dimension, keyed by ``SearchCriteria`` field name."""


# Which catalog entry describes each enum, so coercion can find its labels.
FILTER_BY_ENUM: dict[type[Enum], str] = {
    Activity: "activities",
    Geography: "geographies",
    Hoa: "hoa",
    HousingType: "housing_types",
    LandUse: "land_uses",
    MarketStatus: "market_statuses",
    SaleType: "sale_type",
}


def _normalise(text: str) -> str:
    """Reduce free-form input to a comparable key."""
    return "".join(
        character if character.isalnum() else "-" for character in text.strip().lower()
    ).strip("-")


@lru_cache(maxsize=None)
def _aliases(enum_cls: type[Enum]) -> dict[str, Enum]:
    """Every spelling accepted for a member of ``enum_cls``.

    Covers the canonical value, LandWatch's display label and the enum member
    name, so "log-cabin", "Cabin" and "CABIN" all resolve. Labels are only
    registered when unambiguous: the Geography and property type sets both
    contain "Lakefront", and a label shared by two members is dropped rather
    than resolved arbitrarily.
    """
    aliases: dict[str, Enum] = {}
    ambiguous: set[str] = set()

    def offer(key: str, member: Enum) -> None:
        if not key:
            return
        existing = aliases.get(key)
        if existing is not None and existing is not member:
            ambiguous.add(key)
            return
        aliases[key] = member

    spec = FILTER_CATALOG.get(FILTER_BY_ENUM.get(enum_cls, ""))
    labels = {value.value: value.label for value in spec.values} if spec else {}

    for member in enum_cls:
        offer(_normalise(str(member.value)), member)
        offer(_normalise(member.name), member)
        label = labels.get(str(member.value))
        if label:
            offer(_normalise(label), member)

    for key in ambiguous:
        aliases.pop(key, None)
    return aliases


def coerce_value(enum_cls: type[Enum], text: str) -> Enum:
    """Resolve user or model input to an enum member.

    Accepts the canonical value, LandWatch's label or the member name. Raises
    ``ValueError`` listing the canonical values when nothing matches.
    """
    member = _aliases(enum_cls).get(_normalise(text))
    if member is not None:
        return member
    valid = ", ".join(str(item.value) for item in enum_cls)
    label = FILTER_BY_ENUM.get(enum_cls, enum_cls.__name__)
    raise ValueError(f"unknown {label} '{text}'. Valid options: {valid}")


def enumerable_filters() -> dict[str, FilterSpec]:
    """The dimensions offering a genuine choice between named values.

    Excludes booleans and the tristate, whose "values" are just on and off.
    """
    return {
        name: spec
        for name, spec in FILTER_CATALOG.items()
        if spec.values and spec.kind not in (FilterKind.TRISTATE, FilterKind.BOOLEAN)
    }


def describe(name: str) -> str:
    """Render one filter dimension as readable text."""
    spec = FILTER_CATALOG.get(name)
    if spec is None:
        available = ", ".join(sorted(FILTER_CATALOG))
        raise KeyError(f"unknown filter '{name}'. Available: {available}")

    lines = [f"{spec.name}  [{spec.kind.value}]"]
    if spec.section:
        lines.append(f"  LandWatch section: {spec.section}")
    lines.append(f"  {spec.description}")
    lines.append(f"  URL segment: {spec.segment}")

    for heading, entries in (("Values", spec.values), ("Presets", spec.presets)):
        if not entries:
            continue
        lines.append(f"  {heading}:")
        width = max(len(entry.value) for entry in entries)
        for entry in entries:
            identifier = f" (id {entry.id})" if entry.id is not None else ""
            lines.append(f"    {entry.value:<{width}}  {entry.label}{identifier}")

    if spec.notes:
        lines.append(f"  Note: {spec.notes}")
    return "\n".join(lines)


def as_dict() -> dict[str, dict[str, object]]:
    """The catalog as plain JSON-serialisable data."""
    return {
        name: {
            "section": spec.section,
            "kind": spec.kind.value,
            "description": spec.description,
            "segment": spec.segment,
            "values": [
                {"value": v.value, "label": v.label, "segment": v.segment, "id": v.id}
                for v in spec.values
            ],
            "presets": [
                {"value": v.value, "label": v.label, "segment": v.segment} for v in spec.presets
            ],
            "notes": spec.notes,
        }
        for name, spec in FILTER_CATALOG.items()
    }
