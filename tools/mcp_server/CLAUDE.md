# MCP server

FastMCP over streamable-http on `:8010`. One server, shared by every agent, so all four see the same tool vocabulary.

**Not implemented yet.** This brief is the contract to build against.

Agents attach with:

```python
MCPServerAdapter({"url": "http://localhost:8010/mcp", "transport": "streamable-http"})
```

## Exposed tools

| Tool | Wraps | Used by |
| --- | --- | --- |
| `landwatch_search` | `run_search` in `tools/landwatch/landwatch/tools.py` | Scout |
| `landwatch_detail` | `get_detail` in `tools/landwatch/landwatch/search.py` | Enricher |

## The rule that keeps this honest

**Reuse the existing schema and description objects — never retype them.** The LandWatch input model and tool description are already generated from that tool's filter catalog. Re-declaring a filter value list in an MCP schema creates a second source of truth that drifts silently the first time the catalog changes. Import them.

## Rules

- This server is a thin adapter. Business logic, retries, and coercion belong in the tool module, not here.
- Errors surface as structured payloads the calling model can read and retry against, per the contract in `tools/CLAUDE.md`.
- Adding a tool here means the tool already exists under `tools/` with typed I/O, a fixture, and a test. Do not expose a capability through MCP that has no direct test.
- Port 8010 is reserved for this server. Do not run it elsewhere.
