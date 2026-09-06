import { useState } from 'react'
import styles from './RefinementPicker.module.css'

export interface RefinementOption {
  id: string
  section: string
  label: string
  count: number
  /** Acreage/price/location/residence are "primary" and always shown; the
   * rest ("secondary") collapse behind "More filters" once the option set is
   * wide — see agents/supervisor/criteria_gate.py PRIMARY_FACET_SECTIONS. */
  tier?: 'primary' | 'secondary'
}

interface RefinementGroup {
  section: string
  tier: 'primary' | 'secondary'
  options: RefinementOption[]
}

interface RefinementPickerProps {
  options: RefinementOption[]
  totalMatching: number
  analysis?: {
    common_conditions?: string[]
    recommendations?: string[]
  }
  /** Applies every currently-selected option across all facet groups in one turn. */
  onApply: (selected: RefinementOption[]) => Promise<void>
  isLoading: boolean
}

// Sections that describe one mutually-exclusive value or range (you cannot be
// in two counties, or under $500k and under $1M at once) render as radios.
// Everything else (property type, activities, land use, ...) can hold more
// than one true value at a time, so it renders as checkboxes.
const SINGLE_SELECT_SECTIONS = new Set(['City', 'County', 'Region', 'Price', 'Parcel Size', 'Residence', 'HOA'])

function reductionLabel(totalMatching: number, count: number): string {
  if (!totalMatching || count >= totalMatching) return ''
  const percent = Math.round(((totalMatching - count) / totalMatching) * 100)
  return `${percent}% fewer results`
}

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}

function groupBySection(options: RefinementOption[]): RefinementGroup[] {
  const bySection = new Map<string, RefinementGroup>()
  const order: string[] = []
  options.forEach((option) => {
    if (!bySection.has(option.section)) {
      bySection.set(option.section, { section: option.section, tier: option.tier ?? 'secondary', options: [] })
      order.push(option.section)
    }
    bySection.get(option.section)!.options.push(option)
  })
  return order.map((section) => bySection.get(section)!)
}

export default function RefinementPicker({
  options,
  totalMatching,
  analysis,
  onApply,
  isLoading,
}: RefinementPickerProps) {
  const [selected, setSelected] = useState<Record<string, Set<string>>>({})

  if (!options.length) return null

  const groups = groupBySection(options)
  const primaryGroups = groups.filter((g) => g.tier === 'primary')
  const secondaryGroups = groups.filter((g) => g.tier !== 'primary')
  const secondaryCount = secondaryGroups.reduce((sum, g) => sum + g.options.length, 0)

  const toggle = (section: string, optionId: string, exclusive: boolean) => {
    setSelected((prev) => {
      const next = { ...prev }
      const current = new Set(prev[section] ?? [])
      if (exclusive) {
        current.clear()
        if (!(prev[section]?.has(optionId))) current.add(optionId)
      } else if (current.has(optionId)) {
        current.delete(optionId)
      } else {
        current.add(optionId)
      }
      next[section] = current
      return next
    })
  }

  const selectedOptions = groups.flatMap((group) =>
    group.options.filter((option) => selected[group.section]?.has(option.id)),
  )
  const selectedCount = selectedOptions.length

  const handleApply = async () => {
    if (selectedCount === 0) return
    await onApply(selectedOptions)
    setSelected({})
  }

  const renderGroup = (group: RefinementGroup) => {
    const exclusive = SINGLE_SELECT_SECTIONS.has(group.section)
    const groupName = `refine-${slugify(group.section)}`
    return (
      <fieldset key={group.section} className={styles.group}>
        <legend className={styles.groupLegend}>{group.section}</legend>
        <div className={styles.optionList}>
          {group.options.map((option) => {
            const checked = selected[group.section]?.has(option.id) ?? false
            const reduction = reductionLabel(totalMatching, option.count)
            return (
              <label key={option.id} className={styles.optionRow} data-checked={checked || undefined}>
                <input
                  type={exclusive ? 'radio' : 'checkbox'}
                  name={exclusive ? groupName : undefined}
                  checked={checked}
                  onChange={() => toggle(group.section, option.id, exclusive)}
                  disabled={isLoading}
                  className={styles.optionInput}
                />
                <span className={styles.optionLabel}>{option.label}</span>
                <span className={styles.optionCount}>
                  {option.count.toLocaleString()} matches{reduction ? ` · ${reduction}` : ''}
                </span>
              </label>
            )
          })}
        </div>
      </fieldset>
    )
  }

  return (
    <section className={styles.panel} aria-label="Suggested search refinements">
      {analysis?.recommendations?.length ? (
        <p className={styles.summary}>{analysis.recommendations.join(' • ')}</p>
      ) : null}

      <p className={styles.hint}>
        Select one or more filters below and apply them together — or just tell me in the chat, e.g. "under
        $500k and at least 10 acres".
      </p>

      <div className={styles.groups}>{primaryGroups.map(renderGroup)}</div>

      {secondaryGroups.length > 0 && (
        <details className={styles.moreFilters}>
          <summary className={styles.moreFiltersSummary}>More filters ({secondaryCount})</summary>
          <div className={styles.groups}>{secondaryGroups.map(renderGroup)}</div>
        </details>
      )}

      {analysis?.common_conditions?.length ? (
        <p className={styles.note}>{analysis.common_conditions[0]}</p>
      ) : null}

      <div className={styles.applyRow}>
        <span className={styles.selectedCount}>
          {selectedCount > 0 ? `${selectedCount} filter${selectedCount > 1 ? 's' : ''} selected` : 'No filters selected'}
        </span>
        <button
          type="button"
          className={styles.applyButton}
          onClick={() => void handleApply()}
          disabled={isLoading || selectedCount === 0}
        >
          Apply {selectedCount > 0 ? `${selectedCount} filter${selectedCount > 1 ? 's' : ''}` : 'filters'}
        </button>
      </div>
    </section>
  )
}
