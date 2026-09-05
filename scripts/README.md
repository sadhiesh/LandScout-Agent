# Scripts

## Service Management Scripts

Shell scripts for starting, stopping, and managing LandScout services:

- **`run.sh`** — Start all services (API, agents, MCP, datastores) with auto-install
- **`stop.sh`** — Cleanly stop all services and containers
- **`reload.sh`** — Reload a single service without restarting everything
- **`restart-agents.sh`** — Restart only the agent services
- **`getModels.sh`** — Query available models from the Engineering AI Gateway

Run from the repo root: `./scripts/run.sh`

## Data Generation Scripts

Periodic and bulk jobs that run **outside** the agent loop — refreshes, backfills, one-off maintenance. Nothing here is called during a user request.

Tool-specific generators stay with their tool. LandWatch's live-fetching scripts are at `tools/landwatch/scripts/`:

- `build_geography.py` — refresh the bundled place dataset (51 throttled live requests).
- `build_filters_doc.py` — regenerate `FILTERS.md` from the filter catalog.

## Conventions

- A script that hits a live source states its request count and rate limit in its module docstring, so nobody runs it casually.
- Scripts are idempotent and safe to re-run.
- Output goes to a tracked artifact path, never to stdout as the only result.
- Anything an agent needs during a run belongs in `tools/`, not here.
