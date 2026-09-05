# Tests

Cross-cutting tests for agents and the API. **Tool tests live under that tool** — LandWatch's suite is at `tools/landwatch/tests/` and stays there.

```
tests/
├── agents/     routing, memory short-circuit, contract between supervisor and workers
├── api/        endpoint contracts, /debug read-only guarantees
└── fixtures/   captured responses shared across agent and API tests
```

## Rules

- **No live network calls.** Every external response is a committed fixture. This is not a preference — see `docs/decisions/0003`.
- Capture one real response per source, per scenario, and replay it. If a live grammar change breaks a test, refresh the fixture rather than loosening the assertion.
- Agent tests stub the LLM. Assert on routing, tool selection, and contracts, not on generated prose.
- The memory short-circuit deserves a dedicated test: identical criteria on a follow-up must **not** re-dispatch to Scout. That behavior is the point of the memory layer and it is easy to regress silently.
- API tests must assert that no `/debug/*` route can trigger an agent invocation or an outbound call.

## Running

```bash
pytest tests/                  # this folder
pytest tools/landwatch/tests/  # LandWatch client
```
