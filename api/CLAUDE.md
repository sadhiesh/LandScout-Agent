# API layer

FastAPI on `:8000`. This is the **only** thing the UI talks to. Three categories of endpoint, kept strictly separate.

| Route | Behavior |
| --- | --- |
| `POST /chat` | Invokes the Supervisor via `asyncio.to_thread()` (to avoid blocking the event loop) and returns the result. Accepts optional `selected_parcel_ids` (1–10) for legacy pending parcel-selection turns, optional `selected_refinement_id` / `selected_refinement_ids` (plural takes precedence) for one or more options chosen from the latest pending facet-narrowing turn, plus optional `llm_provider` / `llm_model` for per-request model selection. The product surface. Never exposes a raw tool or adapter function. |
| `GET /config/models` | **Read-only.** Returns the LLM provider and model catalog from `config/models.yaml` plus per-provider availability flags (e.g., `openrouter` unavailable if `OPENROUTER_API_KEY` is empty). No agent invocation, no live external call. |
| `GET /events/{run_id}` | SSE stream of trace events for the live run, fanned out from the in-process event bus. Replays buffered events then streams new ones with heartbeat. |
| `POST /internal/trace` | Internal-only ingest for worker agents to post trace events to the bus. Not exposed to UI. |
| `GET /debug/*` | **Read-only.** Serves what was already captured in Postgres or the event bus replay buffer. |
| `GET /debug/sessions/{session_id}/trace` | **Read-only.** All persisted trace events across every run in a session, ordered by timestamp — the session-scoped counterpart to `GET /debug/runs/{run_id}/trace`. Backs the Observability panel's cross-turn history (see `ui-next/CLAUDE.md`). |
| `GET /debug/logs/stream` | SSE stream of all service logs (api, supervisor, scout, enricher, scorer, mcp), tailed in real-time. |
| `GET /debug/logs/tail` | Backfill of recent log lines for a service or all services. |
| `GET /health` | Liveness only. |

## The read-only rule

A `/debug/*` endpoint never triggers an agent invocation and never makes a live external API call. Debug views read what already happened; they do not cause new things to happen. If a debug view needs data that is not being captured, fix the capture in the agent or trace layer — do not have the endpoint go fetch it.

## Conventions

- Request and response bodies are Pydantic models. No bare dicts across the boundary.
- Every request gets a `run_id` at the edge and threads it through every trace event and audit line. The debug console is useless without it.
- Errors return a structured body with a stable `error` field. Do not leak stack traces to the UI.
- Auth: none. Single user, local use. See `docs/decisions/` for why this differs from a multi-tenant design.
- The API imports agent entry points; it does not reimplement routing. Any "just this once" business logic here belongs in the Supervisor.
- Blocking synchronous calls (A2A client, orchestrate_pipeline) are run via `asyncio.to_thread()` to prevent event loop freezes.
- `api/chat.py` is the sole writer of final assistant messages. Supervisor
  branches return outcomes; duplicating a final write in an agent produces
  duplicate history rows.

## Files

- `main.py` — app assembly, middleware, `run_id` injection, `/health`, static file serving for the React UI at `/static/dist/`.
- `chat.py` — wraps the Supervisor invoke (via `asyncio.to_thread()`) and streams responses. Validates `llm_provider` / `llm_model`, forwards structured parcel or refinement selections to the supervisor, and persists the final assistant payload.
- `config_routes.py` — catalog endpoint (`GET /config/models`). Read-only, no agent invocation.
- `events.py` — in-process event bus for trace events; `/internal/trace` ingest, `/events/{run_id}` SSE fan-out.
- `logs_stream.py` — SSE streaming of all service logs for the Raw Logs tab.
- `debug.py` — read-only views over audit logs and memory tables.
