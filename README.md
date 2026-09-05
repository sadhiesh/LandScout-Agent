# LandScout Agent

Multi-agent land investment research system that turns plain-language criteria into a ranked shortlist of parcels with defensible rationales.

## Overview

LandScout uses four specialized agents (Supervisor, Scout, Enricher, Scorer) to orchestrate land parcel research:

1. **Scout** (:8002) - Searches LandWatch for parcels matching investment criteria
2. **Enricher** (:8003) - Gathers additional facts (price history, county comparables)
3. **Scorer** (:8004) - Ranks parcels using deterministic weighted scoring
4. **Supervisor** (:8001) - Orchestrates the pipeline with memory short-circuiting

The system includes:
- **API** (:8000) - FastAPI gateway with /chat and /events endpoints
- **MCP Server** (:8010) - Shared tool vocabulary for all agents
- **Memory** - Postgres for durable storage, Redis for trace pub/sub
- **UI** - React + TypeScript investor console with observability

## Quick Start

### Prerequisites

- Python >= 3.10, < 3.14 (CrewAI constraint)
- Docker and docker-compose (for Postgres/Redis)
- `uv` package manager

### Installation

```bash
# Clone or navigate to the repository
cd "LandScout Agent"

# The run.sh script will automatically:
# - Create .venv if it doesn't exist
# - Install dependencies if not installed
# Just run:
./run.sh

# Or install manually first:
uv venv
uv pip install -e ".[agents,dev]"

# Copy and configure environment file (required)
cp config/.env.example .env
# Edit .env with your LLM gateway configuration
```

**Important**: You must configure `.env` with your LLM gateway settings before the agents will work. See `config/.env.example` for required variables.

### Running

```bash
# Start all services (auto-installs dependencies if needed)
./scripts/run.sh

# Stop all services
./scripts/stop.sh

# UI is served at http://localhost:8000
# Or run in dev mode: cd ui-next && npm run dev

# Or manually start services:
# 1. docker-compose up -d
# 2. .venv/bin/python memory/migrate.py
# 3. Start each agent/service individually
```

Services will start on these ports:
- API: http://localhost:8000
- Supervisor: http://localhost:8001
- Scout: http://localhost:8002
- Enricher: http://localhost:8003
- Scorer: http://localhost:8004
- MCP: http://localhost:8010

### Usage

1. Navigate to http://localhost:8000 in your browser
2. Enter a natural language request like:
   - "Find 20-50 acre parcels in Texas under $500k"
   - "Show me recreational land in Nevada with water access"
3. The system will search, enrich, score, and return a ranked shortlist

## Architecture

```
Browser → API (:8000) → Supervisor (:8001)
                          ├─ Scout (:8002) ──┐
                          ├─ Enricher (:8003)├─→ MCP (:8010) → LandWatch
                          └─ Scorer (:8004)  ─┘
```

- **Agent-to-Agent (A2A)**: HTTP-based protocol for agent communication
- **MCP**: Model Context Protocol for shared tool access
- **Memory**: Postgres + Redis for state management
- **Tracing**: Redis pub/sub for live SSE streaming to UI

## Configuration

### Scoring Weights

Edit `config/criteria.yaml` to adjust scoring dimensions:

```yaml
weights:
  value_vs_comps: 0.30      # Price vs county comparables
  acreage_fit: 0.15          # How well acres match criteria
  criteria_match: 0.20       # Matches search filters
  water_and_terrain: 0.10    # Water features, topography
  access_and_utilities: 0.15 # Road access, utilities
  market_signal: 0.10        # Days on market, price cuts
```

### Enrichment Sources

Enable/disable enrichers in `tools/enrichment/`:
- ✅ `landwatch_detail` - Price history, full descriptions
- ✅ `county_comps` - County median price comparisons
- ❌ `flood_fema` - FEMA flood zones (disabled stub)
- ❌ `soil_usda` - USDA soil quality (disabled stub)
- ❌ `zoning` - Zoning information (disabled stub)

To enable a stub, implement it and record an ADR in `docs/decisions/`.

## Testing

```bash
# Run all tests
pytest

# Run specific suite
pytest tools/landwatch/tests/  # LandWatch client (offline)
pytest tests/                    # Cross-cutting tests
```

## Development

### Project Structure

```
agents/          # Four A2A agents (supervisor, scout, enricher, scorer)
api/             # FastAPI layer (:8000)
config/          # criteria.yaml, data_sources.yaml, .env.example
docs/            # architecture.md, decisions/ ADRs
logs/            # Audit logging (runtime, gitignored)
memory/          # Postgres migrations and store interfaces
tools/           # LandWatch client, MCP server, enrichment, scoring
ui-next/         # React + TypeScript investor console UI
```

### Key Files

- `CLAUDE.md` - Root context map (read first)
- `prompt.md` - Product specification
- `docs/architecture.md` - Full system architecture
- Each agent has an `AGENT.md` defining its role and contract

### Adding an Agent

1. Create `agents/<name>/AGENT.md` with role, tools, contract
2. Assign a port in `docs/architecture.md`
3. Implement as CrewAI Agent wrapped in A2ACrewServer
4. Wire into Supervisor routing only (never worker-to-worker)

### Adding an Enricher

1. Create `tools/enrichment/<name>.py` with `@register` decorator
2. Follow the `Enricher` protocol (name, enabled, enrich())
3. Never invent data - return `None` for unavailable facts
4. Add test fixture and unit test

## Memory & Caching

The system caches results based on criteria fingerprints:
- Every initial or amended search shows the complete merged criteria and waits
  for explicit confirmation before cache lookup or Scout
- Follow-up questions with unchanged criteria return cached scores
- No re-running the pipeline for "Show me the top 3" after "Find parcels in Texas"
- Fingerprint is SHA256 of canonical JSON criteria

## Decisions

See `docs/decisions/` for ADRs:
- 0001: Folder-local context files
- 0005: CrewAI native OpenAI provider
- 0006: Phased UI development
- 0007: Async CrewAI execution in A2A server

## Contributing

1. Read `CLAUDE.md` first - it's the project map
2. Run `twining_assemble` before working on agents/
3. Add ADRs for non-obvious decisions
4. Record changes with `twining_record` before committing
5. Use `black` for Python formatting

## Status

**Current**: Implementation complete, ready for production testing
- ✅ All infrastructure (config, LLM, datastores, schemas, trace)
- ✅ All agents (Supervisor, Scout, Enricher, Scorer)
- ✅ MCP server and enrichment registry
- ✅ Deterministic scoring system
- ✅ API layer with SSE streaming
- ✅ React + TypeScript investor console UI
- ✅ Async CrewAI execution (ADR 0007)
- ✅ A2A protocol implementation
- ⏳ End-to-end integration tests
- ⏳ Production deployment

### Known Limitations

**Network Sandbox**: When running in sandboxed environments, LLM gateway calls may fail with `ConnectionError`. The system architecture and A2A communication work correctly; this is an environmental network restriction, not a code defect. In production or with `required_permissions: ["all"]`, full functionality is available.

## License

See LICENSE file.

## Contact

For questions or issues, file a GitHub issue or see `docs/`.

---

**Built with**: Python, CrewAI, FastAPI, Postgres, Redis, A2A Protocol, MCP
