# LandScout Agent

---

# READ FIRST

This file is read on **every** session, so it stays short and is mostly pointers. Local context lives next to the code it describes — always read the nearest `CLAUDE.md` / `AGENT.md` before editing a folder.

| File / Location | Content Summary | When to Read |
| --- | --- | --- |
| `CLAUDE.md` (this file) | Project purpose, folder map, global gotchas, how to run tests. | Every session, before any change. |
| `prompt.md` | Product spec: criteria → parcels → enrich → score → shortlist with memory. 3-panel UI. Simplicity mandate. | Every session. Before adding agents, UI, memory, or scoring. |
| `docs/architecture.md` | Full multi-agent architecture, ports, data flow, trace model. | Before scaffolding a new service, port, or cross-agent flow. |
| `docs/agent-contracts.md` | Canonical data structures between agents and tools. Standard schema for parcels, enrichments, scores. | Before adding a tool, data source, or modifying agent I/O. |
| `docs/decisions/` | ADRs — one short file per settled non-obvious tradeoff. | Before re-litigating any design choice. Append a new ADR when you settle one. |
| `agents/AGENT_CARDS.md` | Canonical CrewAI Agent cards (role, goal, backstory, tools) for all agents in the A2A system. | Before modifying any agent's card or understanding the agent topology. |
| `agents/<name>/AGENT.md` | That agent's role, owned tools, inputs/outputs, failure behavior. | Before editing that agent or changing its tool allowlist. |
| `tools/CLAUDE.md` | Shared tool conventions: typed I/O, error contract. | Before adding or editing any tool adapter. |
| `tools/landwatch/CLAUDE.md` | LandWatch client brief: URL grammar, HTTP/2 rules, catalog SSOT, tests. | Before any change under `tools/landwatch/`. |
| `memory/CLAUDE.md` | What is persisted vs ephemeral; the memory contract. | Before adding a persisted field or touching `memory/schema/`. |
| `api/CLAUDE.md` | Endpoint contract; the only seam between UI and agents. | Before adding or changing an endpoint. |
| `ui-next/CLAUDE.md` | Frontend stack and conventions (React + TypeScript, separate from Python backend). | Before editing anything under `ui-next/`. |
| `config/criteria.yaml` | Current investment criteria and scoring weights. | Before changing scoring behavior. |
| `pyproject.toml` | Python package, deps, CLI scripts. | Prior to changing build, install, or dependencies. |

---

# MISSION & PROJECT OVERVIEW

Turn plain-language land-investment criteria into a ranked shortlist of parcels with defensible rationales, and persist memory so follow-ups do not re-run the pipeline. Single user; no multi-tenant auth or entitlement layer.

Python `>=3.10` (CrewAI pins `<3.14`), Pydantic v2, `httpx[http2]`, Typer, pytest. Planned and not yet installed: CrewAI + LiteLLM, FastMCP, FastAPI/uvicorn, Postgres, Redis. The UI is a separate React/TypeScript stack under `ui/`.

**Status: mid-build.** Only `tools/landwatch/` is implemented. Every other folder is scaffolding with a local context file and no runtime code yet. Do not assume a module exists because its folder does.

---

# DECISION FILTER

**Simplicity & Maintainability > Type Safety & Single Source of Truth > Correctness of search grammar and scoring defensibility > Debuggability (logging / tracing) > Performance**

- Prefer a small readable module over a new abstraction. `prompt.md` forbids over-engineering.
- Never restate a tool's vocabulary in prompts, MCP schemas, or docs — derive it from that tool's catalog.
- Scorer rationales must come from the deterministic score breakdown only.
- Do not add caches, services, or HTTP optimizations without a measured failure.

---

# ARCHITECTURE & FILE MAP

## Directory Structure

- `agents/` — one folder per agent, each with an `AGENT.md` (role + tool allowlist) beside its implementation. Supervisor is the only agent that calls other agents.
- `api/` — FastAPI seam between UI and agents. `/chat` invokes the supervisor; `/debug/*` is read-only.
- `ui-next/` — React + TypeScript investor console. Ocean Blue shell with Observability and Parcels tabs, live SSE narration, model selection, themes, and full Inspector overlay.
- `tools/` — data-source and capability adapters. `landwatch/` (implemented), `enrichment/`, `scoring/`, `mcp_server/`.
- `skills/` — reusable methodology loaded on demand (`SKILL.md` per skill), not on every turn.
- `memory/` — `schema/` SQL migrations are the persisted contract (tracked); scratchpad state is ephemeral.
- `config/` — `criteria.yaml`, `data_sources.yaml`, `.env.example`. No secrets.
- `logs/` — `README.md` documents the audit schema; `logs/audit/` contents are gitignored runtime output.
- `tests/` — cross-cutting agent and API tests. Tool-specific tests stay under that tool.
- `docs/` — `architecture.md`, `data-source-reference.md`, and `decisions/` ADRs.
- `scripts/` — bulk/periodic jobs run outside the agent loop.
- `.claude/commands/` — slash commands for repeatable workflows.

## Entry Points

- API: `api/main.py` — `/chat`, `/debug/*`, `/health`.
- Agents: `agents/<name>/<name>.py`, described by `agents/<name>/AGENT.md`.
- LandWatch CLI: `landwatch` console script → `tools/landwatch/landwatch/cli.py`.
- MCP: `tools/mcp_server/` exposes tools to agents over streamable-http.
- Ports (do not invent others): UI/API `:8000`, Supervisor `:8001`, Scout `:8002`, Enricher `:8003`, Scorer `:8004`, MCP `:8010`, Postgres `:5432`, Redis `:6379`.

---

# WORKSPACE RULES & CONVENTIONS

## File Naming & Structure

- Python: `snake_case` modules and functions, `PascalCase` classes, `UPPER_SNAKE` constants and enum members.
- TypeScript/React: `PascalCase.tsx` components, `camelCase` functions. See `ui/CLAUDE.md`.
- Tests: `test_<module>.py`. Tool tests live under that tool; cross-cutting tests in `tests/`.
- `from __future__ import annotations` on new Python modules. Type hints on public functions; `Any` only at JSON/HTTP edges.
- Every new top-level folder gets a `CLAUDE.md`; every new agent gets an `AGENT.md`; every new skill gets a `SKILL.md`.

## Placement Rules

- A tool's client, tests, and scripts stay inside `tools/<tool>/`. Do not fork a second client elsewhere.
- The UI never imports Python agent or tool code. It talks to `api/` over HTTP only.
- Persisted fields require a migration in `memory/schema/` plus an update to `memory/CLAUDE.md`.
- Anything an agent needs only occasionally belongs in `skills/`, not in a `CLAUDE.md`.
- Long-form rationale belongs in `docs/`, linked from here — never pasted into this file.

## State & Error Handling

- Pydantic input models use `extra="forbid"` unless a tool brief says otherwise. Do not mutate models in place; use `model_copy(update=...)`.
- Library and CLI code raises typed exceptions. Agent/MCP boundaries return structured errors the model can read and retry. See `tools/CLAUDE.md`.
- Log with `logging.getLogger(__name__)`. No print-debugging in library code. Every tool call writes a structured audit line — see `logs/README.md`.
- Never hardcode secrets. The LLM gateway key is short-lived and fetched at process start, never written to `.env`.

---

# OUTPUT & DELIVERY RULES

- Write every created or edited file to its real relative path before claiming the task is done.
- On completion, report the precise relative paths touched.
- After editing a tool, run that tool brief's test and regeneration steps and say what ran and what failed.
- Do not finish an architecture, setup, or API change without the Architecture Sync protocol below.

---

# ANTI-PATTERNS & WARNINGS

- Do **not** call live external APIs from tests. Replay captured fixtures — LandWatch rate-limits and its grammar changes without notice.
- Do **not** use `requests` or HTTP/1.1 for LandWatch. Its CDN returns a blanket `403` without HTTP/2 **and** the full browser header set.
- Do **not** put tool-specific rules (URL grammar, auth quirks, rate limits) in this file. They belong in that folder's `CLAUDE.md`.
- Do **not** let the UI import agent code directly, or let a `/debug/*` endpoint trigger an agent run or a live API call.
- Do **not** have worker agents call each other. Only the Supervisor routes.
- Do **not** let the Scorer invent rationales absent from the deterministic score breakdown.
- Do **not** hardcode API keys, gateway tokens, or secrets. `config/.env.example` holds placeholders only.
- Do **not** target Python 3.14 (CrewAI pins `<3.14`). Use the project `.venv`, not system Python.
- Do **not** commit `logs/audit/` contents or real `.env` files.
- Do **not** assume a git remote, CI, or Dockerfile exists — none do yet.

---

# RUNNING TESTS

```bash
pytest tools/landwatch/tests/    # LandWatch client — fully offline against fixtures
pytest tests/                    # cross-cutting agent and API tests
```

Fixtures mean the default run needs no network. If a live-site grammar change breaks a test, recapture the fixture rather than loosening the assertion.

---

# DECISION LOG & DOCUMENTATION SYNC WORKFLOW

## Decision Log

Every non-obvious call gets a short ADR in `docs/decisions/`, written **in the same session** it is made. Format: context / decision / consequences, 15–20 lines. Number sequentially (`0003-<slug>.md`).

Also append a row to `DECISION_LOG.md` at the repo root for architectural changes and new modules:

| Date (YYYY-MM-DD) | Change / Decision | Rationale | Files Touched |
| --- | --- | --- | --- |
| 2026-08-23 | Restructured the repo around folder-local context files; root `CLAUDE.md` is now pointers only. | Root is read every session; tool and UI detail is a tax on runs that do not need it. | repo-wide, `CLAUDE.md`, `docs/decisions/0001-*` |

Write decisions as natural sentences: "Chose X over Y — reason".

## Architecture Sync Verification Protocol

Before completing a task that adds or renames packages, ports, env vars, HTTP routes, MCP tools, agent cards, or install steps:

1. Diff what changed against `prompt.md`, `docs/architecture.md`, `pyproject.toml`, and this file.
2. If a tool changed, also diff against `tools/<tool>/CLAUDE.md` and run that brief's regen/test steps.
3. If architecture, setup, or public API changed, **ask the user** whether to update `docs/architecture.md`, the relevant `CLAUDE.md`, or the root `README.md` (which does not exist yet).
4. Do not silently rewrite `prompt.md` or `docs/architecture.md` to match an unapproved implementation. Flag the drift and ask.
