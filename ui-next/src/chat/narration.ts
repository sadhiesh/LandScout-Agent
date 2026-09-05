/**
 * Maps the live trace stream into the adaptive in-chat narration.
 * Terse by default (one line per stage); escalates to a multi-line
 * narrative block only when a stage runs long or hits a warning/error —
 * see memory/ui_wireframe_decisions.md for why ("moderate" cadence for
 * personalization is separate and lives in personalize.ts; this module
 * never mentions the investor's name, by design).
 */

import type { TraceEvent } from '../lib/useTraceStream'
import { groupByStage, latestStage, stageIsComplete, type Stage, type StageGroup } from '../lib/pipelineStages'

export const ESCALATE_MS = 5000

const TERSE: Record<Stage, string> = {
  Parse: 'Reading your criteria...',
  Reasoning: 'Reasoning through your criteria (CoT)...',
  Search: 'Searching listings...',
  Enrich: 'Checking flood zone & county records...',
  Score: 'Scoring parcels against your criteria...',
  Pipeline: 'Working...',
}

const DONE: Record<Stage, string> = {
  Parse: 'Parsed your criteria',
  Reasoning: 'Reasoning complete',
  Search: 'Search complete',
  Enrich: 'Enrichment complete',
  Score: 'Scoring complete',
  Pipeline: 'Done',
}

function statFor(group: StageGroup): string | null {
  for (const e of group.events) {
    const d = e.data
    if (!d) continue
    if (typeof d.total_matching === 'number') return `${d.total_matching} found`
    if (typeof d.returned === 'number') return `${d.returned} returned`
    if (typeof d.completed === 'number' && typeof d.total === 'number') return `${d.completed} of ${d.total}`
  }
  return null
}

export interface NarrationLine {
  stage: Stage
  isActive: boolean
  isComplete: boolean
  expanded: boolean
  headline: string
  detailLines: string[]
  warning: string | null
}

export function buildNarration(events: TraceEvent[], overallComplete: boolean, now: number): NarrationLine[] {
  const groups = groupByStage(events)
  const activeStage = latestStage(events)

  return groups.map((group) => {
    const isComplete = stageIsComplete(group.name, events, !overallComplete)
    const isActive = !overallComplete && group.name === activeStage && !isComplete
    const finished = group.finishedAt ?? now
    const started = group.startedAt ?? now
    const duration = (isActive ? now : finished) - started
    const expanded = group.hasWarning || duration > ESCALATE_MS

    const warningEvent = group.events.find((e) => e.kind === 'error')
    const stat = statFor(group)

    let headline: string
    if (isComplete) {
      headline = stat ? `${DONE[group.name]} — ${stat}` : DONE[group.name]
    } else {
      headline = TERSE[group.name]
      if (expanded && group.name === 'Enrich' && stat) {
        headline = `Still checking flood zone & county records — ${stat}`
      }
    }

    const detailLines = expanded
      ? group.events
          .filter((e) => e.kind !== 'error')
          .slice(-3)
          .map((e) => e.summary)
      : []

    return {
      stage: group.name,
      isActive,
      isComplete,
      expanded,
      headline,
      detailLines,
      warning: warningEvent?.summary ?? null,
    }
  })
}
