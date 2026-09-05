# Agents

One folder per agent. Each holds an `AGENT.md` (role, owned tools, contract) beside its implementation, so tool permissions and routing rules are editable as a document rather than buried in Python.

See `agents/AGENT_CARDS.md` for the canonical CrewAI `Agent` definitions (role, goal, backstory, tools) for all agents in the A2A system.

## Topology

Supervisor is the only agent that calls other agents. Scout, Enricher, and Scorer are leaf services — they never call each other.

```
UI → api/ → supervisor → { scout | enricher | scorer } → tools (via MCP)
```

| Agent | Port | Owns |
| --- | --- | --- |
| `supervisor/` | 8001 | Intent parsing, memory lookup, routing, criteria verification before returning |
| `scout/` | 8002 | Criteria → parcel search |
| `enricher/` | 8003 | Per-parcel fact gathering through the enricher registry |
| `scorer/` | 8004 | Deterministic scoring + rationale generation |

## Conventions

- Every agent is the same small shape: a one-agent CrewAI `Crew` wrapped in an A2A executor. Do not invent a second agent framework or a bespoke orchestration layer.
- An agent's tool allowlist lives in its `AGENT.md` and must match what the code actually attaches. If they diverge, the `AGENT.md` is the intent — fix the code.
- Agents reach tools through the MCP server (`tools/mcp_server/`), not by importing tool modules directly. This keeps one vocabulary for every agent.
- Every routing decision, tool call, and tool result emits a trace event. `kind="thought"` feeds the Deep-Thoughts panel; `route`, `tool_call`, `tool_result`, `error` feed the Logs panel.
- Reusable methodology (scoring rubric, report style, research checklists) belongs in `skills/`, loaded on demand — not pasted into agent prompts.

## Adding an agent

1. Write `agents/<name>/AGENT.md` first: role, owned tools, what it explicitly does not own, input/output contract, failure behavior.
2. Assign a port in the reserved range and record it in `docs/architecture.md` and the root `CLAUDE.md` map.
3. Wire it into the Supervisor's routing only. Never into another worker.
4. Add tests under `tests/agents/`.
