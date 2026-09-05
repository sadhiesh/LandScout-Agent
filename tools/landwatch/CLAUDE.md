# LandWatch tool brief

Read this before editing anything under `tools/landwatch/`. Shared tool conventions are in `tools/CLAUDE.md`; project-level rules are in the repo-root `CLAUDE.md`. User-facing usage is `landwatch/README.md`; the background deep-dive is `docs/data-source-reference.md`.

## Layout

- `landwatch/` — client package: `vocab.py`, `filters.py`, `models.py`, `url.py`, `client.py`, `parse.py`, `search.py`, `places.py`, `cli.py`, `tools.py`.
- `landwatch/data/geography.json` — bundled states/regions/counties. Must ship with the package. Cities are **not** bundled.
- `landwatch/FILTERS.md` — generated filter reference. Do not hand-edit.
- `tests/` — offline pytest against HAR fixtures in `tests/fixtures/`.
- `scripts/build_filters_doc.py` — regenerates `FILTERS.md` from `FILTER_CATALOG`; fails if a dimension is ungrouped.
- `scripts/build_geography.py` — regenerates `geography.json` (51 throttled live requests). Cities excluded on purpose.

## Entry points

- CLI: `landwatch` → `landwatch.cli:main` (Typer: `search`, `url`, `detail`, `filters`, `locations`).
- Library: `from landwatch import search, collect, get_detail, SearchCriteria, build_url`. Package `__version__` is `0.2.0` (out of sync with root `pyproject.toml` `0.1.0`).
- Agent wrappers: `landwatch.tools.run_search` / `build_crewai_tool` / `build_langchain_tool` (tool name `landwatch_search`). MCP must reuse `LandSearchInput`, `TOOL_DESCRIPTION`, `run_search`, and `get_detail` — do not re-declare filter value lists.
- The CrewAI wrapper marks `landwatch_search` as `result_as_answer=True` so
  Scout returns the tool's JSON directly after a successful call. The LLM picks
  arguments; it does not reserialize large listing payloads.

## File map (when to read)

| File | When to read |
| --- | --- |
| `landwatch/README.md` | Usage, URL grammar overview, limitations. |
| `landwatch/FILTERS.md` | Human filter reference. Regenerated; never edit by hand. |
| `landwatch/vocab.py` | Enums, `PropertyType` IntFlag, `SITE_ID=1113`, `BASE_URL`, `RESULTS_PER_PAGE=25`, state FIPS. |
| `landwatch/filters.py` | `FILTER_CATALOG` (SSOT for CLI help, tool descriptions, `FILTERS.md`). `coerce_value` accepts slugs, labels, and member names. |
| `landwatch/models.py` | `SearchCriteria` (`extra="forbid"`), `Listing`, `SearchResult`, `PropertyDetail`. Only one of region/county/city; county/city require state. |
| `landwatch/url.py` | Criteria → canonical path. **Segment order is load-bearing.** Keyword after price/acres/sqft. Property types: bitwise OR. |
| `landwatch/client.py` | HTTP/2 + full browser headers, 1 req/s throttle, retries on 403/429/5xx. `LandWatchError` / `LocationNotFound` / `BlockedError`. |
| `landwatch/parse.py` | JSON → models. Missing/renamed fields → `None`; do not fail the whole search. |
| `landwatch/search.py` | `search`, `search_all`, `collect`, `get_detail`. `validate=True` cross-checks URL vs LandWatch criteria endpoint. |
| `landwatch/tools.py` | Named strings, not bitmasks. Errors as JSON `{"error": ...}`, never raised to the agent. |
| `landwatch/places.py` | Offline states/regions/counties; cities via autocomplete (site caps city facet at 300). |
| `tests/` | Run `pytest tools/landwatch/tests/` from the repo root before finishing. |

## Conventions

- Catalog is the single source of truth. Derive CLI help, agent/MCP descriptions, and `FILTERS.md` from `FILTER_CATALOG` / vocab enums. A mismatch must be a `KeyError` or test failure, not silent drift.
- After catalog edits: `python tools/landwatch/scripts/build_filters_doc.py`.
- Refresh `geography.json` only via `scripts/build_geography.py`. Do not add cities.
- Tests stay **offline** against fixtures. If the live grammar changes, recapture fixtures, then update the catalog.
- Frozen `@dataclass` for `FilterSpec` / `FilterValue`. Combine `PropertyType` with bitwise OR (`|`), never addition.
- Library/CLI raise `LandWatchError` subclasses. Agent/MCP boundary returns JSON errors.
- Coerce user/LLM input through `filters.coerce_value`. Do not reintroduce `rural` / `for_sale` booleans on `SearchCriteria` (folded into `Geography` and `SaleType`).
- Do not mutate models in place; use `model_copy(update=...)`.

## Absolute prohibitions

- Do **not** use `requests` or HTTP/1.1. CDN returns `403` without HTTP/2 **and** the full `BROWSER_HEADERS` set (`sec-ch-ua*`, `sec-fetch-*`, `priority`, matching `referer`).
- Do **not** change URL segment order. Keyword comes **after** price/acres/sqft ranges.
- Do **not** hand-edit `FILTERS.md` or `landwatch/data/geography.json`.
- Do **not** skip, delete, or convert tests to live HTTP.
- Do **not** download `image_urls`; the asset host refuses non-browser clients. Treat them as display links.
- Do **not** remove the 1 req/s throttle.

## Decision log (tool)

| Date (YYYY-MM-DD) | Change / Decision | Rationale | Files Touched |
| --- | --- | --- | --- |
| 2026-08-23 | Catalog is SSOT; `FILTERS.md` generated; `coerce_value` accepts labels + slugs; `Geography`/`SaleType` replaced rural/for_sale booleans; keyword segment follows ranges. | Prevent silent vocabulary drift; match recorded LandWatch URLs and labels. | `landwatch/*`, `scripts/build_filters_doc.py` |
| 2026-08-23 | `max_results` bounds via `field_validator`, not `Field(ge/le)`. | Bedrock Claude rejects JSON Schema `minimum`/`maximum` on integer tool params. | `landwatch/tools.py`, `docs/decisions/0008-*` |
| 2026-08-23 | ~~Every `LandSearchInput` property is required in the exported schema.~~ Reverted 2026-08-29. | Believed to fix Bedrock's grammar-size cap; it does not. | `landwatch/tools.py`, `tests/test_tools_schema.py`, `docs/decisions/0009-*` |
| 2026-08-29 | Bedrock's 343.9MB grammar error is caused by CrewAI's hardcoded `strict: True`, not by this schema. Fixed in `agents/common/llm.py`, not here. Removed the `_require_every_property` hook and softened the "every argument must be supplied" line in `TOOL_DESCRIPTION`. | Grammar size scales with total property count regardless of `required`, and `strict` is what triggers grammar compilation at all. The hook reached only the unused LangChain export — CrewAI rewrites `required` itself and the MCP server builds its schema from its own signature. Do not re-shape this schema to chase that error. | `landwatch/tools.py`, `tests/test_tools_schema.py`, `docs/decisions/0010-*` |
