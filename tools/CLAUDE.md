# Tools

Each subfolder is one capability or data source. Shared conventions live here; per-source quirks live in that subfolder's own `CLAUDE.md`.

| Folder | Purpose | Status |
| --- | --- | --- |
| `landwatch/` | LandWatch parcel search client — library, CLI, and agent tool wrappers. | Implemented |
| `collin_cad/` | Collin Central Appraisal District parcel lookup — geometry, valuation, ownership. | Implemented |
| `fema_flood/` | FEMA National Flood Hazard Layer (NFHL) flood zone lookup from parcel geometry. | Implemented |
| `collin_flood/` | Collin County Bo4 floodplain lookup from parcel geometry. | Implemented |
| `enrichment/` | Per-parcel fact adapters behind a pluggable registry. | Implemented |
| `scoring/` | Deterministic weighted parcel scoring. | Planned |
| `mcp_server/` | Exposes tools to agents over MCP. | Planned |

## Shared contract

**Typed in, typed out.** Every tool takes a Pydantic input model and returns a typed result. No bare kwargs dicts, no stringly-typed enums crossing the boundary.

**Two error styles, by caller:**

- Library and CLI callers get typed exceptions.
- Agent and MCP callers get a JSON `{"error": "..."}` payload with a message the model can act on. A tool never raises into an agent loop — an agent that cannot read the failure cannot retry correctly.

**Names over magic values.** Agent-facing schemas accept named strings, not internal integers or bitmasks. Models handle names far more reliably. Coerce to the internal representation inside the tool.

**Vocabulary has one home.** A tool's accepted values are defined once, in that tool's catalog or enums, and every description, CLI help string, and MCP schema is derived from it. Never hand-copy a value list into a prompt or schema — a copy is a silent drift waiting to happen.

## Rules

- A tool's client, tests, scripts, and brief all stay under `tools/<tool>/`. Do not fork a second client elsewhere in the repo.
- Tests replay captured fixtures. Never call a live external API from a test.
- Rate limits and auth requirements are documented in the owning subfolder's `CLAUDE.md`, and enforced in code — not left to the caller to remember.
- Shared transport helpers get one implementation. If two sources need the same client pattern, extract it rather than writing a second one.

## Adding a tool

1. Create `tools/<name>/CLAUDE.md` first, covering auth, rate limits, and the vocabulary source.
2. Add the adapter with typed I/O and the error contract above.
3. Capture a fixture from a real response and commit it.
4. Add a test that runs against the fixture.
5. Register it in `config/data_sources.yaml` (base URL and rate limit, no secrets) and in `tools/mcp_server/` if agents need it.
6. If the tool is a standalone importable package (`tools/<name>/<name>/`), add it to `[tool.setuptools] packages` and `[tool.setuptools.package-dir]` in `pyproject.toml`, then reinstall (`uv pip install -e ".[agents,dev]"`). Do not add `sys.path` or `PYTHONPATH` entries.
