"""Discover and validate the places LandWatch can search.

LandWatch's place vocabulary splits into two halves, and this module reflects
that split:

States, regions and counties are enumerable, so they ship in
``data/geography.json`` and resolve offline. A state-level search response lists
every region and county LandWatch indexes for that state, which is untruncated
but covers only counties it actually has listings for: Texas returns all 254,
while Kansas returns 103 of its 105.

Cities are different. LandWatch caps its own per-state city facet at exactly 300
entries, so a bundled list would be silently truncated. Cities therefore resolve
through the live autocomplete endpoint instead.

Everything degrades gracefully: with ``data/geography.json`` absent, all lookups
fall back to autocomplete, and only the offline listing functions become empty.
"""

from __future__ import annotations

import json
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from .vocab import (
    STATE_ABBREVIATIONS,
    STATE_FIPS,
    STATE_SLUG_TO_ABBREVIATION,
    slugify,
)

DATA_PATH = Path(__file__).parent / "data" / "geography.json"


class PlaceKind(str, Enum):
    """What sort of place this is, and which ``SearchCriteria`` field it fills."""

    STATE = "state"
    REGION = "region"
    COUNTY = "county"
    CITY = "city"


# LandWatch's numeric `type` in autocomplete responses.
_AUTOCOMPLETE_KINDS: dict[int, PlaceKind] = {
    1: PlaceKind.CITY,
    2: PlaceKind.COUNTY,
    5: PlaceKind.REGION,
    6: PlaceKind.STATE,
}


class Place(BaseModel):
    """A location LandWatch can search."""

    name: str = Field(description="Display name, e.g. 'Grayson County'.")
    slug: str = Field(description="The value to pass to SearchCriteria, e.g. 'grayson'.")
    kind: PlaceKind
    landwatch_id: int | None = Field(
        default=None, description="LandWatch's internal id. For states this is the FIPS code."
    )
    state: str | None = Field(
        default=None, description="Two-letter abbreviation of the containing state."
    )

    def criteria_kwargs(self) -> dict[str, str]:
        """The ``SearchCriteria`` arguments that search this place."""
        if self.kind is PlaceKind.STATE:
            return {"state": self.slug}
        if self.state is None:
            raise ValueError(f"{self.kind.value} '{self.name}' has no state, so it cannot be searched")
        return {"state": self.state, self.kind.value: self.slug}


@lru_cache(maxsize=1)
def _dataset() -> dict[str, dict]:
    """Load the bundled geography, or an empty mapping if it has not been built."""
    try:
        raw = DATA_PATH.read_text()
    except OSError:
        return {}
    try:
        return json.loads(raw).get("states", {})
    except (ValueError, AttributeError):
        return {}


def dataset_available() -> bool:
    """Whether the bundled geography dataset has been generated."""
    return bool(_dataset())


def _state_key(state: str) -> str | None:
    """Normalise a state name, slug or abbreviation to its two-letter code."""
    key = state.strip().lower()
    if key in STATE_FIPS:
        return key
    slug = slugify(STATE_ABBREVIATIONS.get(key, key))
    return STATE_SLUG_TO_ABBREVIATION.get(slug)


def find_state(state: str) -> Place | None:
    """Resolve a state name, slug or abbreviation. Works entirely offline."""
    key = _state_key(state)
    if key is None:
        return None
    slug = STATE_ABBREVIATIONS[key]
    entry = _dataset().get(key, {})
    return Place(
        name=entry.get("name") or slug.replace("-", " ").title(),
        slug=slug,
        kind=PlaceKind.STATE,
        landwatch_id=STATE_FIPS[key],
        state=key.upper(),
    )


def list_states() -> list[Place]:
    """Every state LandWatch searches: the 50 states plus the District of Columbia."""
    states = (find_state(key) for key in sorted(STATE_FIPS))
    return [state for state in states if state is not None]


# The dataset keys, spelled out because "county" does not pluralise mechanically.
_DATASET_KEYS: dict[PlaceKind, str] = {
    PlaceKind.REGION: "regions",
    PlaceKind.COUNTY: "counties",
}


def _list_places(state: str, kind: PlaceKind) -> list[Place]:
    key = _state_key(state)
    if key is None or kind not in _DATASET_KEYS:
        return []
    entries = _dataset().get(key, {}).get(_DATASET_KEYS[kind], [])
    return [
        Place(
            name=entry["name"],
            slug=entry["slug"],
            kind=kind,
            landwatch_id=entry.get("id"),
            state=key.upper(),
        )
        for entry in entries
    ]


def list_regions(state: str) -> list[Place]:
    """Every LandWatch region in ``state``. Requires the bundled dataset."""
    return _list_places(state, PlaceKind.REGION)


def list_counties(state: str) -> list[Place]:
    """Every county in ``state``. Requires the bundled dataset."""
    return _list_places(state, PlaceKind.COUNTY)


def parse_autocomplete(entries: list[dict]) -> list[Place]:
    """Turn raw autocomplete entries into :class:`Place` objects.

    Entries of an unrecognised ``type`` are dropped rather than guessed at.
    """
    places: list[Place] = []
    for entry in entries:
        kind = _AUTOCOMPLETE_KINDS.get(entry.get("type"))
        if kind is None:
            continue

        name = entry.get("location") or ""
        search_path = entry.get("searchPath") or ""
        state_id = entry.get("stateId") or 0
        state = _abbreviation_for_fips(state_id)

        places.append(
            Place(
                name=name,
                slug=_slug_from_search_path(search_path, kind, state),
                kind=kind,
                landwatch_id=entry.get("id"),
                state=state.upper() if state else None,
            )
        )
    return places


@lru_cache(maxsize=1)
def _fips_to_abbreviation() -> dict[int, str]:
    return {fips: abbreviation for abbreviation, fips in STATE_FIPS.items()}


def _abbreviation_for_fips(state_id: int) -> str | None:
    return _fips_to_abbreviation().get(state_id)


_KIND_SUFFIXES: dict[PlaceKind, str] = {
    PlaceKind.COUNTY: "-county",
    PlaceKind.REGION: "-region",
}


def _slug_from_search_path(search_path: str, kind: PlaceKind, state: str | None) -> str:
    """Reduce an autocomplete ``searchPath`` to the slug SearchCriteria expects.

    Autocomplete returns fully qualified paths, whereas the criteria fields take
    the bare name that url.py then re-decorates: ``Grayson-County-TX`` becomes
    ``grayson`` and ``Houston-Texas-Region`` becomes ``houston``. Note those two
    put the state and kind suffixes in opposite orders, so this strips whichever
    matches until neither does.
    """
    slug = slugify(search_path)
    if kind is PlaceKind.STATE:
        return slug

    suffixes = []
    if kind in _KIND_SUFFIXES:
        suffixes.append(_KIND_SUFFIXES[kind])
    if state:
        suffixes.append(f"-{state}")
        suffixes.append(f"-{STATE_ABBREVIATIONS[state]}")

    # At most one suffix of each sort, so two passes settle it.
    for _ in range(len(suffixes)):
        for suffix in suffixes:
            if slug.endswith(suffix) and len(slug) > len(suffix):
                slug = slug[: -len(suffix)]
                break
        else:
            break

    return slug


def resolve(
    query: str,
    *,
    kind: PlaceKind | None = None,
    state: str | None = None,
    client: object | None = None,
) -> list[Place]:
    """Find places matching ``query``, offline first and over the network if needed.

    States, regions and counties come from the bundled dataset. Anything not found
    there, including every city, falls through to LandWatch's autocomplete
    endpoint. Pass ``kind`` to restrict the result and ``state`` to scope the
    offline search.

    ``client`` accepts an existing :class:`~landwatch.client.LandWatchClient` so a
    caller can share one connection; one is created per call otherwise.
    """
    matches = _resolve_offline(query, kind=kind, state=state)
    if matches:
        return matches
    return _resolve_online(query, kind=kind, client=client)


@lru_cache(maxsize=1)
def _slug_index() -> dict[str, tuple[tuple[str, PlaceKind], ...]]:
    """Map every bundled slug to the (state, kind) pairs carrying it.

    Slugs repeat heavily across states, so this returns all matches. Indexing up
    front keeps ``resolve`` from walking several thousand counties per call.
    """
    index: dict[str, list[tuple[str, PlaceKind]]] = {}
    for abbreviation, entry in _dataset().items():
        for kind, key in _DATASET_KEYS.items():
            for place in entry.get(key, []):
                index.setdefault(place["slug"], []).append((abbreviation, kind))
    return {slug: tuple(pairs) for slug, pairs in index.items()}


def _query_targets(query: str, kind: PlaceKind | None) -> list[tuple[str, PlaceKind | None]]:
    """The slugs to look for, and the kind each one implies.

    The index stores bare names, so "Grayson County" has to be tried as
    ``grayson`` too, which also pins the kind to county.
    """
    target = slugify(query)
    if not target:
        return []

    targets: list[tuple[str, PlaceKind | None]] = [(target, kind)]
    for suffix, implied in _KIND_SUFFIXES_BY_NAME:
        if target.endswith(suffix) and len(target) > len(suffix) and kind in (None, implied):
            targets.append((target[: -len(suffix)], implied))
    return targets


_KIND_SUFFIXES_BY_NAME: tuple[tuple[str, PlaceKind], ...] = (
    ("-county", PlaceKind.COUNTY),
    ("-region", PlaceKind.REGION),
)


def _resolve_offline(query: str, *, kind: PlaceKind | None, state: str | None) -> list[Place]:
    targets = _query_targets(query, kind)
    if not targets:
        return []

    matches: list[Place] = []
    scope = _state_key(state) if state else None

    if kind in (None, PlaceKind.STATE):
        found = find_state(query)
        if found is not None and found.slug == targets[0][0]:
            matches.append(found)

    for target, target_kind in targets:
        for abbreviation, candidate_kind in _slug_index().get(target, ()):
            if target_kind not in (None, candidate_kind):
                continue
            if scope is not None and abbreviation != scope:
                continue
            matches.extend(
                place
                for place in _list_places(abbreviation, candidate_kind)
                if place.slug == target
            )

    return matches


def _resolve_online(
    query: str, *, kind: PlaceKind | None, client: object | None
) -> list[Place]:
    from .client import LandWatchClient

    if client is not None:
        entries = client.autocomplete_payload(query)  # type: ignore[attr-defined]
    else:
        with LandWatchClient() as owned:
            entries = owned.autocomplete_payload(query)

    places = parse_autocomplete(entries)
    if kind is not None:
        places = [place for place in places if place.kind is kind]
    return places
