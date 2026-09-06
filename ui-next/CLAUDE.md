# UI — Investor Console

The primary React + TypeScript + Vite frontend for LandScout.

Talks only to `api/` over HTTP, same contract as `ui/` (`docs/agent-contracts.md`, `api/CLAUDE.md`). Never imports Python agent or tool code.

## Features

- **Ocean Blue investor shell** (Icon rail | optional Sessions | Chat | Right Workspace) via `lib/usePanelLayout.ts` — native CSS grid + drag, no pane-splitting library. The old 4-column layout key is versioned out.
- **User-controlled right workspace** (`workspace/RightWorkspace.tsx`) — Observability and Parcels tabs. Observability is the default; live events and arriving results never auto-switch it.
- **LLM provider and model selection** (`lib/ModelPicker.tsx`) — per-request choice of provider (eng_ai, OpenRouter) and model, fetched from `GET /config/models` (`lib/useModelCatalog.ts`). Persisted to `landscout-next-llm-provider` / `landscout-next-llm-model` localStorage. Rendered in the composer control row beside skip-cache toggle. Unavailable providers (e.g., OpenRouter without `OPENROUTER_API_KEY`) are disabled with a hint. Reasoning models flagged with ⚡.
- **Observability view** (`rail/TransparencyRail.tsx`) — per-stage accordion with status, timing, confidence/sources, SSE-driven updates, and `Open Inspector`. `lib/useTraceStream.ts` keeps the live SSE stream (`panels`) scoped to the current turn only, but moves each finished turn into an accumulating `history` list instead of discarding it, so a multi-turn session's reasoning trace stays visible (collapsed, oldest first) instead of being wiped on the next message. `history` hydrates from `GET /debug/sessions/{session_id}/trace` on session load/switch and resets only when the session itself changes.
- **Parcel report flow** (`results/`) — compact cards in chat and parcel lists open a full right-pane report; Back returns to the ranked list. Deterministic evidence stays separate from labeled model-generated considerations.
- **Adaptive live narration** (`chat/narration.ts`, `chat/NarrationBubble.tsx`) — terse one-line-per-stage status in the chat pane while a run is active, escalating to detail only past a duration threshold or on warning/error.
- **Moderate-cadence personalization** (`chat/personalize.ts`) — name-aware copy at greeting, milestone delivery, memory-callback, and error moments only. Never used in narration or on every turn.
- **Dedicated Showcase Mode** (`showcase/ShowcaseMode.tsx`) — full-bleed live agent org-chart for the capstone demo, driven by the same `/events/{run_id}` trace. Reasoning-mode badge is read from event data, never hardcoded, so it can't claim Tree-of-Thoughts is active when only Chain-of-Thought is implemented.
- **5 named themes** (`lib/ThemeContext.tsx`) — Ocean (default), Daylight, Midnight, Terra, and Command share one semantic token contract; `suggestTheme()` can switch to Command on Showcase entry without overriding a manual choice.
- **Full-screen Inspector overlay** (`inspector/InspectorOverlay.tsx`) — the same 8 tabs as `ui/src/debug`, but 7 of them share one generic `EventList.tsx` renderer instead of 7 near-duplicate panel components.

## Conventions

Same as `ui/CLAUDE.md`: `PascalCase.tsx` components, `useThing.ts` hooks, CSS modules only, no Tailwind, no UI framework. `ShortlistCard.tsx` reads the canonical `parcel.enrichment` field (`docs/agent-contracts.md`) with a `parcel.enrichments` fallback for compatibility with the older payload shape.

Interactive UI must use semantic tokens from `src/index.css`; component modules do not hardcode theme colors. Preserve visible `:focus-visible` treatment, meaningful icon labels, and the global reduced-motion fallback. On small screens, Chat and Right Workspace are separate user-selected panes.

## Build and serve

- `npm run dev` → Vite dev server on `:5174` with proxy to API `:8000`.
- `npm run build` → outputs to `ui-next/dist/` with `base: '/static/'`.
- Production build is mounted at `/static/` by `api/main.py` and served at http://localhost:8000/
