# LandScout Agent

Multi-agent land investment research system that turns plain-language criteria into a ranked, defensible shortlist of parcels — and remembers the conversation so follow-ups never re-run the pipeline.

## Overview

LandScout uses four specialised agents orchestrated by a Supervisor. Each agent is an independent HTTP service; only the Supervisor routes between them.

| Agent | Port | Responsibility |
|---|---|---|
| **Supervisor** | :8001 | Parses intent, manages memory, gates and routes the pipeline |
| **Scout** | :8002 | Searches LandWatch for matching parcels and facet counts |
| **Enricher** | :8003 | Adds county comparables, CAD data, flood data per parcel |
| **Scorer** | :8004 | Deterministic weighted ranking + prose rationale |
| **API gateway** | :8000 | FastAPI — `/chat`, `/events/{run_id}` SSE, `/debug/*` |
| **MCP server** | :8010 | Shared tool vocabulary (streamable-HTTP) for all agents |

## Pipeline

```
User message
  │
  ▼ Supervisor: parse intent → apply as criteria patch
  │
  ├─ Stage 1 gate: no actionable signal? → ask one question, stop
  │
  ▼ Criteria confirmation: show full merged criteria, wait for yes/no
  │
  ├─ Memory fingerprint match? → answer from Postgres, stop
  │
  ▼ Scout: search LandWatch → listings + facet counts
  │
  ├─ Stage 2 gate: total_matching > shortlist_size?
  │    └─ yes → validate facets, offer refinement options, stop
  │    └─ zero results → name narrowest filter, offer to drop it, stop
  │
  ▼ Enricher: per-parcel facts (CAD, flood, detail)
  │
  ▼ Scorer: deterministic weighted score + rationale per parcel
  │
  ▼ Supervisor: verify shortlist, return ranked results
```

### Key pipeline guarantees

- **No invented constraints** — the only default is `state: texas`; price bands, acreage bands, and property types are never supplied on the user's behalf.
- **Criteria provenance** — every field is tagged `user`, `inferred`, or `default`. Inferred locations (e.g. "McKinney" → Texas) surface in the confirmation and require explicit approval before a search runs.
- **Facet-guided narrowing** — Stage 2 converts LandWatch's own facet counts into catalog-validated criteria patches. Only options that represent a genuine subset of the current criteria (including correct range intersection checks) are presented.
- **Keyword hygiene** — purpose/intent words like "investment", "resale", "flip" are stripped from the `keyword` search field; they describe the buyer's goal, not a land feature.
- **Rationales are auditable** — the Scorer writes prose only from the deterministic score breakdown it is handed. It cannot invent a claim absent from that breakdown.
- **Memory short-circuit** — SHA-256 fingerprint of canonical criteria JSON; identical fingerprint = Postgres answer, no re-search, no re-scoring.

## Quick Start

### Prerequisites

- Python ≥ 3.10, < 3.14 (CrewAI constraint)
- Node.js 18+ (for `ui-next/` only)
- Postgres :5432 and Redis :6379 running locally
- An LLM gateway (OpenAI-compatible endpoint)

### Installation

```bash
cd "LandScout Agent"

# Create virtualenv and install all dependencies
uv venv
uv pip install -e ".[agents,dev]"

# Copy and configure environment (required before first run)
cp config/.env.example .env
# Fill in LLM_GATEWAY_URL, LLM_MODEL, and gateway credentials
```

### Running the backend

```bash
# Start all five services (Supervisor, Scout, Enricher, Scorer, API)
./scripts/run.sh

# Stop all services
./scripts/stop.sh

# Reload a single agent without stopping others
./scripts/reload.sh <agent-name>
```

Services start on the ports listed in the Overview table. The API gateway (`localhost:8000`) is the only public-facing entry point.

### Running the UI

```bash
# Development mode (hot reload) — runs on :5174
cd ui-next
npm install
npm run dev

# Production build
npm run build
```

> The UI dev server runs on `:5174`. The backend does not yet serve the built UI bundle automatically.

### First request

```
POST localhost:8000/chat
{"session_id": "<uuid>", "user_id": "<uuid>", "message": "20 acres in Collin County, Texas under $500k"}
```

Or open `http://localhost:5174` after starting the UI dev server.

## Configuration

### Environment variables

See `config/.env.example`. Required keys:

| Variable | Purpose |
|---|---|
| `LLM_GATEWAY_URL` | OpenAI-compatible base URL |
| `LLM_MODEL` | Model name sent to the gateway |
| `DATABASE_URL` | Postgres connection string |
| `REDIS_URL` | Redis connection string |

### Scoring weights

All weights live in `config/criteria.yaml`. They must sum to 1.0; dimensions without data are dropped and the rest renormalized.

```yaml
weights:
  value_vs_comps:       0.25   # Ask price / acre vs county median
  criteria_match:       0.15   # How well the parcel matches stated filters
  acreage_fit:          0.12   # Deviation from requested size
  land_use_fit:         0.10   # Raw/ag vs improved land categories
  developability:       0.10   # Parcel compactness, split precedent
  access_and_utilities: 0.10   # Road access, utility availability
  tax_burden:           0.08   # Entity count, MUDs, TIFs, ag rollback
  water_and_terrain:    0.05   # Flood zone tier, usable acreage discount
  market_signal:        0.05   # Days on market, tenure, owner-occupancy
```

Bump `version` in `criteria.yaml` on any weight change; scores record it so a historical ranking is traceable to the weights that produced it.

The last three dimensions (`tax_burden`, `water_and_terrain`, `market_signal`) read Collin County Appraisal District data and renormalize away rather than scoring zero outside Collin County.

### Shortlist size

```yaml
shortlist_size: 10
```

Stage 2 triggers when Scout reports `total_matching > shortlist_size`. Change this to tune where facet narrowing kicks in.

## Enrichment sources

Enrichers are registered in `tools/enrichment/`. A failing enricher is logged and skipped — never fatal.

| Enricher | Status | Data |
|---|---|---|
| `landwatch_detail` | ✅ enabled | Full description, price history, photos |
| `county_comps` | ✅ enabled | Collin CAD median $/acre, comparable parcels |
| `fema_flood` | ✅ registered | FEMA flood zone overlay, usable-acreage discount |
| `collin_flood` | ✅ registered | County flood layer cross-referenced with FEMA |
| `usda_soil` | ❌ stub | USDA soil quality — implement and record an ADR to enable |
| `zoning` | ❌ stub | Zoning data — implement and record an ADR to enable |

## Testing

```bash
# LandWatch client — fully offline, runs against captured fixtures
pytest tools/landwatch/tests/

# Cross-cutting agent and API tests
pytest tests/

# Full suite (excludes live-LLM tests that need network credentials)
pytest tools/landwatch/tests/ tests/ --ignore=tests/test_llm_connection.py
```

Fixtures mean the default run needs no network. If a LandWatch grammar change breaks a test, recapture the fixture — do not loosen the assertion.

## UI — investor console (`ui-next/`)

A React + TypeScript investor console designed for transparency.

**Layout**: Sessions rail | Chat | Right workspace (Observability / Parcels tabs)

**Themes**: Ocean (default), Daylight, Midnight, Terra, Command

**Key features**:

- **Transparency Rail** — live SSE narration per pipeline stage; `Reasoning (CoT)` accordion shows the Supervisor's chain-of-thought before any tool fires.
- **Facet refinement** — when Stage 2 narrows, validated options appear as a `RefinementPicker`; clicking one applies the stored criteria patch and reruns Scout without re-showing the confirmation form.
- **8-tab Inspector** — score breakdown, raw enrichment data, trace logs, criteria provenance, and more; opened from the Rail footer.
- **Showcase Mode** — full-bleed animated org-chart driven by the same `/events/{run_id}` trace the console uses.
- **Session continuity** — previous runs reload their full trace from Postgres on session switch.

## Project structure

```
agents/
  supervisor/          # Orchestrator — criteria gate, memory, routing
  scout/               # LandWatch search + facet parsing
  enricher/            # Per-parcel fact gathering
  scorer/              # Deterministic scoring + rationale
  common/              # A2A client, trace emitter, LLM builder

api/                   # FastAPI gateway (:8000) — /chat, /events, /debug/*

config/
  criteria.yaml        # Scoring weights, gate thresholds, flood config
  .env.example         # Required env var template

docs/
  architecture.md      # Full system design, ports, data flow, trace model
  agent-contracts.md   # Canonical data structures between agents and tools
  decisions/           # 31 ADRs — one per settled non-obvious trade-off

memory/
  schema/              # Numbered SQL migrations (apply in order)
  store.py             # Postgres read/write helpers

skills/                # Reusable methodology loaded on demand (not on every turn)
  criteria-parsing/    # LLM prompt template for turn_resolution extraction
  criteria-sufficiency/ # Stage 1 + Stage 2 gate prompt templates
  parcel-research-checklist/
  report-writing-style/
  scoring-methodology/

tools/
  landwatch/           # HTTP/2 search client — the only implemented tool adapter
  collin_cad/          # Collin County appraisal data
  collin_flood/        # County flood layer
  fema_flood/          # FEMA flood zone overlay
  mcp_server/          # FastMCP server exposing tools to agents
  enrichment/          # Enricher registry and adapters
  scoring/             # Deterministic scoring engine

ui-next/               # React + TypeScript investor console (:5174 dev)

scripts/               # run.sh, stop.sh, reload.sh, restart-agents.sh

tests/                 # Cross-cutting tests (agent, API)
logs/                  # Runtime audit logs (gitignored)
```

## Architecture decisions

31 ADRs are in `docs/decisions/`. Notable ones:

| ADR | Decision |
|---|---|
| 0002 | API is the only seam between UI and agents |
| 0004 | Deterministic scoring + generated prose (rationale cannot invent claims) |
| 0018 | Criteria sufficiency gate — two-stage, deterministic triggers |
| 0027 | Mandatory criteria confirmation before every search |
| 0029 | Scout returns tool result directly (no intermediate LLM paraphrase) |
| 0031 | Tiered multi-select facet narrowing |

## Development conventions

- **Python**: `snake_case` modules/functions, `PascalCase` classes, `UPPER_SNAKE` constants. `from __future__ import annotations` on every new module.
- **TypeScript**: `PascalCase.tsx` components, `camelCase` functions.
- **New agent**: add `AGENT.md` + port in `docs/architecture.md`, implement as `CrewAI Agent` in `A2ACrewServer`, wire into Supervisor only.
- **New enricher**: `@register` decorator in `tools/enrichment/`, never fatal, record an ADR.
- **New persisted field**: SQL migration in `memory/schema/` (number sequentially) + update `memory/CLAUDE.md`.
- **Secrets**: never in `.env` or committed files; the LLM key is fetched at process start from the gateway.
- **LandWatch**: must use HTTP/2 + full browser header set; its CDN returns a blanket 403 without them. Never use `requests` or HTTP/1.1 for LandWatch calls.

## Status

**Mid-build** — core pipeline implemented and tested; some advanced enrichers remain as stubs.

| Area | State |
|---|---|
| LandWatch search client | ✅ Complete — offline fixture tests |
| Criteria parsing + provenance | ✅ Complete |
| Stage 1 sufficiency gate | ✅ Complete |
| Criteria confirmation loop | ✅ Complete |
| Memory fingerprint + short-circuit | ✅ Complete |
| Facet-guided narrowing (Stage 2) | ✅ Complete |
| Generic keyword filtering | ✅ Complete |
| A2A protocol + tracing | ✅ Complete |
| Deterministic scoring engine | ✅ Complete |
| Collin CAD enrichment | ✅ Complete |
| FEMA / county flood enrichment | ✅ Complete |
| API gateway + SSE streaming | ✅ Complete |
| React investor console (`ui-next/`) | ✅ Complete |
| USDA soil / zoning enrichers | ❌ Stubs — not implemented |
| `docker-compose.yml` / `Dockerfile` | ❌ Not yet |
| End-to-end integration tests | ⏳ Partial |
| Root `README.md` → rendered docs | ⏳ This file |

## Known limitations

- **Collin County only** for CAD-backed dimensions (`tax_burden`, `value_vs_comps`, some scoring sub-dims). Those dimensions renormalize away outside Collin County rather than scoring zero.
- **LandWatch rate limit** — Scout enforces 1 req/s. Live calls in tests are forbidden; use fixtures.
- **Network sandbox** — in sandboxed CI environments, LLM gateway calls may fail with `ConnectionError`. This is an environmental restriction, not a code defect.

## License

See `LICENSE`.

---

**Built with**: Python 3.10+, CrewAI 1.15, FastAPI, FastMCP, Pydantic v2, httpx (HTTP/2), Postgres, Redis, React 18, TypeScript 5, Vite 5
