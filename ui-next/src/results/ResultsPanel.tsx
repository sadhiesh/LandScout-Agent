import { useMemo, useState } from 'react'
import ShortlistCard, { type Parcel } from './ShortlistCard'
import type { TraceEvent } from '../lib/useTraceStream'
import { latestStage, stageIsComplete, type Stage } from '../lib/pipelineStages'
import { sortParcels, topScoringParcel, type SortMode } from './resultSemantics'
import styles from './ResultsPanel.module.css'

interface ResultsPanelProps {
  parcels: Parcel[]
  totalMatching: number
  isRunActive: boolean
  events: TraceEvent[]
  onSelectParcel: (parcel: Parcel) => void
}

const SEARCH_STAGES: Stage[] = ['Search', 'Enrich', 'Score']

export default function ResultsPanel({ parcels, totalMatching, isRunActive, events, onSelectParcel }: ResultsPanelProps) {
  const [sortMode, setSortMode] = useState<SortMode>('score')
  const sortedParcels = useMemo(() => sortParcels(parcels, sortMode), [parcels, sortMode])
  const topParcel = useMemo(() => topScoringParcel(parcels), [parcels])
  const activeStage = latestStage(events)

  return (
    <section className={styles.panel}>
      <header className={styles.header}>
        <div>
          <div className={styles.title}>Top parcel recommendations</div>
          <div className={styles.sub}>
            {parcels.length === 0
              ? isRunActive
                ? 'Building your ranked shortlist'
                : 'Your ranked shortlist will appear here'
              : isRunActive
                ? `Updating recommendations — showing ${parcels.length} previous results`
              : `Showing ${parcels.length} of ${totalMatching || parcels.length} matches`}
          </div>
        </div>
        {parcels.length > 1 && (
          <div className={styles.tools}>
            <select className={styles.sort} value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)} aria-label="Sort parcel results">
              <option value="score">Sort: Match score</option>
              <option value="price">Sort: Price</option>
              <option value="acres">Sort: Acreage</option>
            </select>
          </div>
        )}
      </header>

      {parcels.length > 0 && isRunActive && (
        <div className={styles.refreshBanner} role="status" aria-live="polite">
          <span className={styles.refreshDot} aria-hidden />
          <div>
            <div className={styles.refreshTitle}>Agents are refreshing this shortlist</div>
            <div className={styles.refreshText}>Previous results remain visible until the new run finishes.</div>
          </div>
        </div>
      )}

      {parcels.length > 0 && (
        <div className={styles.banner}>
          <div className={styles.bannerIcon}>✨</div>
          <div>
            <div className={styles.bannerTitle}>Agent recommendation</div>
            <div className={styles.bannerText}>
              Top picks are ranked by your criteria. Open a card for the score breakdown and enrichment sources.
            </div>
          </div>
        </div>
      )}

      {parcels.length === 0 && isRunActive ? (
        <div className={styles.searching}>
          <div className={styles.orbit} aria-hidden>
            <span />
          </div>
          <div className={styles.emptyTitle}>Searching for the best parcels</div>
          <div className={styles.emptySub}>Agents are searching, enriching, and scoring properties against your criteria.</div>
          <div className={styles.searchSteps}>
            {SEARCH_STAGES.map((stage) => {
              const isComplete = stageIsComplete(stage, events, isRunActive)
              const isCurrent = activeStage === stage && !isComplete
              return (
                <div key={stage} className={`${styles.searchStep} ${isComplete ? styles.stepSeen : ''} ${isCurrent ? styles.stepCurrent : ''}`}>
                  <span>{isComplete ? '✓' : isCurrent ? '●' : '○'}</span>
                  {stage === 'Search' ? 'Searching listings' : stage === 'Enrich' ? 'Gathering property data' : 'Analyzing and scoring'}
                </div>
              )
            })}
          </div>
        </div>
      ) : parcels.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyArt}>◇</div>
          <div className={styles.emptyTitle}>Start with your investment criteria</div>
          <div className={styles.emptySub}>
            Describe acreage, region, budget, and intended use in chat. Parcels stay here until you choose to open them.
          </div>
        </div>
      ) : (
        <div className={styles.list}>
          {sortedParcels.map((parcel, idx) => (
            <ShortlistCard
              key={parcel.property_id || idx}
              parcel={parcel}
              rank={idx + 1}
              variant="list"
              topPick={parcel === topParcel}
              onSelect={() => onSelectParcel(parcel)}
            />
          ))}
        </div>
      )}
    </section>
  )
}
