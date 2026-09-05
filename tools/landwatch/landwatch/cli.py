"""Command-line interface for LandWatch searches.

Examples::

    landwatch search --state texas --county grayson --price 200000-800000 --acres 5-50
    landwatch search --state texas --region texoma --type farms_and_ranches --type undeveloped \\
        --pages 3 --json results.json --csv results.csv
    landwatch search --state colorado --geography mountain --geography off-grid --keyword cabin
    landwatch url --state colorado --type hunting --acres 40-500
    landwatch filters geographies
    landwatch locations --state tx
    landwatch detail 422653962
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import places
from .client import LandWatchError
from .filters import FILTER_CATALOG, as_dict, coerce_value, describe
from .models import Listing, SearchCriteria, SearchResult
from .search import collect, get_detail
from .url import build_url
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

app = typer.Typer(
    add_completion=False,
    help="Search LandWatch for land listings matching structured criteria.",
)


def _parse_range(value: str | None, label: str) -> tuple[float | None, float | None]:
    """Parse ``MIN-MAX``, ``MIN-`` or ``-MAX`` into a pair of bounds."""
    if not value:
        return None, None
    text = value.strip()
    if "-" not in text:
        raise typer.BadParameter(f"{label} must look like MIN-MAX, MIN- or -MAX (got '{value}')")
    low, _, high = text.partition("-")
    try:
        return (float(low) if low.strip() else None, float(high) if high.strip() else None)
    except ValueError as exc:
        raise typer.BadParameter(f"{label} bounds must be numbers (got '{value}')") from exc


def _as_int(value: float | None) -> int | None:
    return int(value) if value is not None else None


def _combine_types(names: list[str]) -> PropertyType | None:
    """Combine ``--type`` names into a single bitmask."""
    if not names:
        return None
    combined: PropertyType | None = None
    for name in names:
        key = name.strip().upper().replace("-", "_")
        try:
            flag = PropertyType[key]
        except KeyError as exc:
            valid = ", ".join(sorted(n.lower() for n in PropertyType.__members__))
            raise typer.BadParameter(f"unknown property type '{name}'. Choose from: {valid}") from exc
        combined = flag if combined is None else combined | flag
    return combined


def _enum_list(values: list[str], enum_cls) -> list:
    return [_enum_value(value, enum_cls) for value in values]


def _enum_value(value: str | None, enum_cls):
    """Coerce one string into ``enum_cls``, reporting the valid values on failure."""
    if value is None:
        return None
    try:
        return coerce_value(enum_cls, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _build_criteria(
    *,
    state: str | None = None,
    region: str | None = None,
    county: str | None = None,
    city: str | None = None,
    price: str | None = None,
    acres: str | None = None,
    sqft: str | None = None,
    beds: int | None = None,
    baths: int | None = None,
    types: list[str] | None = None,
    activities: list[str] | None = None,
    geographies: list[str] | None = None,
    land_uses: list[str] | None = None,
    housing_types: list[str] | None = None,
    status: list[str] | None = None,
    hoa: str | None = None,
    sale_type: str | None = None,
    keyword: str | None = None,
    residence: bool | None = None,
    owner_financing: bool = False,
    mineral_rights: bool = False,
    rural: bool = False,
    reduced_days: int | None = None,
    sort_order_id: int | None = None,
    page: int = 1,
) -> SearchCriteria:
    price_min, price_max = _parse_range(price, "--price")
    acres_min, acres_max = _parse_range(acres, "--acres")
    sqft_min, sqft_max = _parse_range(sqft, "--sqft")

    selected = _enum_list(geographies or [], Geography)
    # --rural is kept as a shorthand for the geography value of the same name.
    if rural and Geography.RURAL not in selected:
        selected.append(Geography.RURAL)

    try:
        return SearchCriteria(
            state=state,
            region=region,
            county=county,
            city=city,
            price_min=_as_int(price_min),
            price_max=_as_int(price_max),
            acres_min=acres_min,
            acres_max=acres_max,
            sqft_min=_as_int(sqft_min),
            sqft_max=_as_int(sqft_max),
            beds_min=beds,
            baths_min=baths,
            property_types=_combine_types(types or []),
            activities=_enum_list(activities or [], Activity),
            geographies=selected,
            land_uses=_enum_list(land_uses or [], LandUse),
            housing_types=_enum_list(housing_types or [], HousingType),
            market_statuses=_enum_list(status or [], MarketStatus),
            hoa=_enum_value(hoa, Hoa),
            sale_type=_enum_value(sale_type, SaleType),
            keyword=keyword,
            has_residence=residence,
            owner_financing=owner_financing,
            mineral_rights=mineral_rights,
            price_reduction_days=reduced_days,
            sort_order_id=sort_order_id,
            page=page,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


CSV_COLUMNS = [
    "property_id",
    "title",
    "price",
    "acres",
    "price_per_acre",
    "city",
    "county",
    "state_abbreviation",
    "zip_code",
    "property_types",
    "beds",
    "baths",
    "home_sqft",
    "latitude",
    "longitude",
    "broker_name",
    "broker_company",
    "url",
]


def _write_csv(listings: list[Listing], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for listing in listings:
            row = listing.model_dump(mode="json")
            writer.writerow(
                {
                    **{key: row.get(key) for key in CSV_COLUMNS if key in row},
                    "property_types": "; ".join(listing.property_types),
                    "broker_name": listing.broker.name if listing.broker else None,
                    "broker_company": listing.broker.company if listing.broker else None,
                }
            )


def _print_table(result: SearchResult) -> None:
    typer.echo(f"\n{result.url}")
    location = result.location_name or "the selected area"
    typer.echo(
        f"{result.total_count:,} listings in {location} "
        f"(showing {len(result.listings)}, page {result.page} of {result.total_pages or 1})\n"
    )
    if result.applied_filters:
        typer.echo("Filters: " + " | ".join(result.applied_filters) + "\n")

    header = f"{'PRICE':>12}  {'ACRES':>9}  {'$/ACRE':>10}  {'LOCATION':<24} TITLE"
    typer.echo(header)
    typer.echo("-" * len(header))
    for listing in result.listings:
        where = f"{listing.city or '?'}, {listing.state_abbreviation or '?'}"
        per_acre = f"${listing.price_per_acre:,.0f}" if listing.price_per_acre else "-"
        typer.echo(
            f"{listing.price_display or '-':>12}  "
            f"{listing.acres_display or '-':>9}  "
            f"{per_acre:>10}  "
            f"{where[:24]:<24} {(listing.title or '')[:44]}"
        )
    typer.echo("")


# Shared option definitions so `search` and `url` accept identical filters.
StateOpt = Annotated[str | None, typer.Option("--state", help="State name or abbreviation.")]
RegionOpt = Annotated[str | None, typer.Option("--region", help="Region name, e.g. 'texoma'.")]
CountyOpt = Annotated[str | None, typer.Option("--county", help="County name, e.g. 'grayson'.")]
CityOpt = Annotated[str | None, typer.Option("--city", help="City name, e.g. 'howe'.")]
PriceOpt = Annotated[str | None, typer.Option("--price", help="Price range, e.g. 100000-500000.")]
AcresOpt = Annotated[str | None, typer.Option("--acres", help="Acreage range, e.g. 10-50.")]
SqftOpt = Annotated[str | None, typer.Option("--sqft", help="Home sq ft range, e.g. 1000-3000.")]
BedsOpt = Annotated[int | None, typer.Option("--beds", help="Minimum bedrooms.")]
BathsOpt = Annotated[int | None, typer.Option("--baths", help="Minimum bathrooms.")]
TypesOpt = Annotated[
    list[str] | None,
    typer.Option("--type", help="Property type; repeatable (farms_and_ranches, hunting, ...)."),
]
ActivitiesOpt = Annotated[
    list[str] | None, typer.Option("--activity", help="Activity; repeatable (fishing, camping, ...).")
]
GeographyOpt = Annotated[
    list[str] | None,
    typer.Option("--geography", help="Terrain; repeatable (mountain, off-grid, desert, ...)."),
]
LandUsesOpt = Annotated[
    list[str] | None, typer.Option("--land-use", help="Land use; repeatable (homestead, pasture, ...).")
]
HousingOpt = Annotated[
    list[str] | None,
    typer.Option("--housing-type", help="Housing type; repeatable (barndominium, cottage, ...)."),
]
StatusOpt = Annotated[
    list[str] | None,
    typer.Option("--status", help="Availability; repeatable (available, under-contract, sold)."),
]
HoaOpt = Annotated[
    str | None, typer.Option("--hoa", help="'hoa-none', 'hoa-mandatory' or 'hoa-voluntary'.")
]
SaleTypeOpt = Annotated[
    str | None, typer.Option("--sale-type", help="'for-sale' or 'auctions'.")
]
KeywordOpt = Annotated[
    str | None, typer.Option("--keyword", help="Free-text search, e.g. 'creek frontage'.")
]
ResidenceOpt = Annotated[
    bool | None, typer.Option("--residence/--no-residence", help="Require or exclude a house.")
]
OwnerFinOpt = Annotated[bool, typer.Option("--owner-financing", help="Owner financing available.")]
MineralOpt = Annotated[bool, typer.Option("--mineral-rights", help="Mineral rights included.")]
RuralOpt = Annotated[
    bool, typer.Option("--rural", help="Shorthand for --geography rural.")
]
ReducedOpt = Annotated[
    int | None, typer.Option("--reduced-days", help="Only price reductions in the last N days.")
]
SortOpt = Annotated[
    int | None,
    typer.Option("--sort-order-id", help="Raw LandWatch sort id; the label mapping is unknown."),
]
PageOpt = Annotated[int, typer.Option("--page", help="Starting page (1-based).")]


@app.command()
def search(
    state: StateOpt = None,
    region: RegionOpt = None,
    county: CountyOpt = None,
    city: CityOpt = None,
    price: PriceOpt = None,
    acres: AcresOpt = None,
    sqft: SqftOpt = None,
    beds: BedsOpt = None,
    baths: BathsOpt = None,
    types: TypesOpt = None,
    activities: ActivitiesOpt = None,
    geographies: GeographyOpt = None,
    land_uses: LandUsesOpt = None,
    housing_types: HousingOpt = None,
    status: StatusOpt = None,
    hoa: HoaOpt = None,
    sale_type: SaleTypeOpt = None,
    keyword: KeywordOpt = None,
    residence: ResidenceOpt = None,
    owner_financing: OwnerFinOpt = False,
    mineral_rights: MineralOpt = False,
    rural: RuralOpt = False,
    reduced_days: ReducedOpt = None,
    sort_order_id: SortOpt = None,
    page: PageOpt = 1,
    pages: Annotated[int, typer.Option("--pages", help="How many pages to fetch.")] = 1,
    limit: Annotated[int | None, typer.Option("--limit", help="Stop after N listings.")] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write full results to a JSON file.")
    ] = None,
    csv_out: Annotated[
        Path | None, typer.Option("--csv", help="Write a listing summary to a CSV file.")
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", help="Suppress the results table.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Log request activity.")] = False,
) -> None:
    """Search LandWatch and print or export the matching listings."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    criteria = _build_criteria(
        state=state, region=region, county=county, city=city,
        price=price, acres=acres, sqft=sqft, beds=beds, baths=baths,
        types=types, activities=activities, geographies=geographies,
        land_uses=land_uses, housing_types=housing_types, status=status,
        hoa=hoa, sale_type=sale_type, keyword=keyword, residence=residence,
        owner_financing=owner_financing, mineral_rights=mineral_rights, rural=rural,
        reduced_days=reduced_days, sort_order_id=sort_order_id, page=page,
    )

    try:
        result = collect(criteria, max_pages=max(1, pages), max_listings=limit)
    except LandWatchError as exc:
        typer.secho(f"Search failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if not quiet:
        _print_table(result)

    if json_out:
        json_out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"Wrote {len(result.listings)} listings to {json_out}")
    if csv_out:
        _write_csv(result.listings, csv_out)
        typer.echo(f"Wrote {len(result.listings)} listings to {csv_out}")


@app.command()
def url(
    state: StateOpt = None,
    region: RegionOpt = None,
    county: CountyOpt = None,
    city: CityOpt = None,
    price: PriceOpt = None,
    acres: AcresOpt = None,
    sqft: SqftOpt = None,
    beds: BedsOpt = None,
    baths: BathsOpt = None,
    types: TypesOpt = None,
    activities: ActivitiesOpt = None,
    geographies: GeographyOpt = None,
    land_uses: LandUsesOpt = None,
    housing_types: HousingOpt = None,
    status: StatusOpt = None,
    hoa: HoaOpt = None,
    sale_type: SaleTypeOpt = None,
    keyword: KeywordOpt = None,
    residence: ResidenceOpt = None,
    owner_financing: OwnerFinOpt = False,
    mineral_rights: MineralOpt = False,
    rural: RuralOpt = False,
    reduced_days: ReducedOpt = None,
    page: PageOpt = 1,
) -> None:
    """Print the search URL for the given criteria without making a request."""
    criteria = _build_criteria(
        state=state, region=region, county=county, city=city,
        price=price, acres=acres, sqft=sqft, beds=beds, baths=baths,
        types=types, activities=activities, geographies=geographies,
        land_uses=land_uses, housing_types=housing_types, status=status,
        hoa=hoa, sale_type=sale_type, keyword=keyword, residence=residence,
        owner_financing=owner_financing, mineral_rights=mineral_rights, rural=rural,
        reduced_days=reduced_days, page=page,
    )
    typer.echo(build_url(criteria))


@app.command()
def detail(
    property_id: Annotated[int, typer.Argument(help="LandWatch property id.")],
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write the detail to a JSON file.")
    ] = None,
) -> None:
    """Fetch full detail, including price history, for one listing."""
    try:
        result = get_detail(property_id)
    except LandWatchError as exc:
        typer.secho(f"Lookup failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"\n{result.title or 'Listing'} ({result.property_id})")
    typer.echo(f"{result.url or ''}")
    price = f"${result.price:,.0f}" if result.price else "-"
    typer.echo(f"\nPrice   : {price}")
    typer.echo(f"Acres   : {result.acres or '-'}")
    typer.echo(f"Location: {result.address or '-'}, {result.city or '-'} {result.state_abbreviation or ''}")
    typer.echo(f"County  : {result.county or '-'}")
    typer.echo(f"Types   : {', '.join(result.property_types) or '-'}")
    typer.echo(f"MLS     : {result.mls_id or '-'}   Listed: {result.listed_date or '-'}")
    if result.broker:
        typer.echo(f"Broker  : {result.broker.name or '-'} ({result.broker.company or '-'})")
    if result.price_history:
        typer.echo("\nPrice history:")
        for event in result.price_history:
            amount = f"${event.price:,.0f}" if event.price else "-"
            # Format the date as a string first: applying a width spec directly to a
            # date object routes to strftime and emits the spec literally.
            when = str(event.date) if event.date else "?"
            typer.echo(f"  {when:<12} {event.event:<18} {amount}")
    if result.description:
        typer.echo(f"\n{result.description[:600]}")
    typer.echo("")

    if json_out:
        json_out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"Wrote detail to {json_out}")


@app.command("filters")
def list_filters(
    name: Annotated[
        str | None,
        typer.Argument(help="A single filter to describe, e.g. 'geographies'. Omit for all."),
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit the catalog as JSON instead of text.")
    ] = False,
) -> None:
    """Show every filter LandWatch accepts and its possible values."""
    if json_out:
        typer.echo(json.dumps(as_dict() if name is None else {name: as_dict()[name]}, indent=2))
        return

    if name is not None:
        try:
            typer.echo("\n" + describe(name) + "\n")
        except KeyError as exc:
            raise typer.BadParameter(str(exc).strip('"')) from exc
        return

    typer.echo(f"\n{len(FILTER_CATALOG)} filter dimensions:\n")
    for spec in FILTER_CATALOG.values():
        count = f"{len(spec.values)} values" if spec.values else ""
        if spec.presets and not spec.values:
            count = f"{len(spec.presets)} presets"
        typer.echo(f"  {spec.name:<21} {spec.kind.value:<12} {count}")
    typer.echo("\nRun 'landwatch filters <name>' for the values of one filter.\n")


@app.command("locations")
def list_locations(
    query: Annotated[
        str | None, typer.Argument(help="A place name to look up, e.g. 'grayson' or 'texoma'.")
    ] = None,
    state: Annotated[
        str | None, typer.Option("--state", help="List every region and county in this state.")
    ] = None,
    kind: Annotated[
        str | None, typer.Option("--kind", help="Restrict to state, region, county or city.")
    ] = None,
) -> None:
    """Find the places LandWatch can search.

    With --state, lists that state's regions and counties from the bundled data.
    With a query, resolves a name, falling back to LandWatch's live autocomplete.
    """
    if state:
        for label, found in (
            ("Regions", places.list_regions(state)),
            ("Counties", places.list_counties(state)),
        ):
            typer.echo(f"\n{label} in {state} ({len(found)}):")
            if not found:
                typer.echo("  (none; run scripts/build_geography.py to build the dataset)")
            for place in found:
                typer.echo(f"  {place.slug:<28} {place.name}")
        typer.echo("")
        return

    if not query:
        found = places.list_states()
        typer.echo(f"\n{len(found)} states:\n")
        for place in found:
            typer.echo(f"  {place.slug:<24} {place.state}  (id {place.landwatch_id})")
        typer.echo("\nPass a place name, or --state ABBR to list its regions and counties.\n")
        return

    kind_filter = _enum_value(kind, places.PlaceKind)
    try:
        found = places.resolve(query, kind=kind_filter)
    except LandWatchError as exc:
        typer.secho(f"Lookup failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if not found:
        typer.secho(f"No place matched '{query}'.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"\n{len(found)} match(es) for '{query}':\n")
    for place in found:
        typer.echo(
            f"  {place.kind.value:<7} {place.slug:<26} {place.state or '--'}  {place.name}"
        )
    typer.echo("")


def main() -> None:
    """Entry point for the ``landwatch`` console script."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        typer.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
