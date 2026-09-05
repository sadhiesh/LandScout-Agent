# Logs

This folder contains service logs (`*.log`) — stdout/stderr from each running service (gitignored)

## Service Logs

Each service writes to its own log file:

- `api.log` — API server (port 8000)
- `supervisor.log` — Supervisor agent (port 8001)
- `scout.log` — Scout agent (port 8002)
- `enricher.log` — Enricher agent (port 8003)
- `scorer.log` — Scorer agent (port 8004)
- `mcp.log` — MCP server (port 8010)

These files capture standard output and errors from each service. Use `tail -f logs/*.log` to monitor all services in real-time.

## Trace System

**TraceEvent schema:**

| Field | Type | Notes |
| --- | --- | --- |
| `run_id` | string | Minted by `api/` at the edge. Joins to every memory table. |
| `ts` | ISO-8601 string | UTC |
| `agent` | string | `supervisor`, `scout`, `enricher`, `scorer` |
| `kind` | string | `thought`, `route`, `a2a_send`, `a2a_recv`, `tool_call`, `tool_result`, `error`, `subagent_start`, `subagent_finish`, `memory_read`, `memory_write`, `context` |
| `summary` | string | Short human-readable description |
| `data` | object or null | Structured detail for debug inspection (tool args/results, context payloads, etc.) |

## Rules

- `run_id` is mandatory on every line. A line without one cannot be traced and is a bug in the caller.
- Never log secrets, API keys, or auth headers. Redact before writing.
- The debug console reads these files through `/debug/*`. Changing a field name here breaks `ToolCallInspector.tsx` — update both.
- Truncate large payloads rather than dropping the line. A truncated record is still traceable; a missing one is not.
