import type { TraceEvent, TurnRecord } from '../lib/useTraceStream'
import ParcelDetail from '../results/ParcelDetail'
import ResultsPanel from '../results/ResultsPanel'
import type { Parcel } from '../results/ShortlistCard'
import TransparencyRail from '../rail/TransparencyRail'
import styles from './RightWorkspace.module.css'

export type WorkspaceTab = 'observability' | 'parcels'

interface RightWorkspaceProps {
  activeTab: WorkspaceTab
  onTabChange: (tab: WorkspaceTab) => void
  events: TraceEvent[]
  history: TurnRecord[]
  parcels: Parcel[]
  totalMatching: number
  isRunActive: boolean
  selectedParcel: Parcel | null
  onSelectParcel: (parcel: Parcel) => void
  onBackToResults: () => void
  onOpenInspector: () => void
}

export default function RightWorkspace({
  activeTab,
  onTabChange,
  events,
  history,
  parcels,
  totalMatching,
  isRunActive,
  selectedParcel,
  onSelectParcel,
  onBackToResults,
  onOpenInspector,
}: RightWorkspaceProps) {
  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const next: WorkspaceTab = activeTab === 'observability' ? 'parcels' : 'observability'
    onTabChange(next)
    document.getElementById(`${next}-tab`)?.focus()
  }

  return (
    <aside className={styles.workspace} aria-label="Search workspace">
      <div className={styles.tabs} role="tablist" aria-label="Workspace views">
        <button
          type="button"
          id="observability-tab"
          role="tab"
          aria-selected={activeTab === 'observability'}
          tabIndex={activeTab === 'observability' ? 0 : -1}
          aria-controls="observability-panel"
          className={`${styles.tab} ${activeTab === 'observability' ? styles.active : ''}`}
          onClick={() => onTabChange('observability')}
          onKeyDown={onTabKeyDown}
        >
          <span aria-hidden>◎</span> Observability
          {isRunActive && <span className={styles.liveDot} aria-label="Live run" />}
        </button>
        <button
          type="button"
          id="parcels-tab"
          role="tab"
          aria-selected={activeTab === 'parcels'}
          tabIndex={activeTab === 'parcels' ? 0 : -1}
          aria-controls="parcels-panel"
          className={`${styles.tab} ${activeTab === 'parcels' ? styles.active : ''}`}
          onClick={() => onTabChange('parcels')}
          onKeyDown={onTabKeyDown}
        >
          <span aria-hidden>◇</span> Parcels
          {parcels.length > 0 && <span className={styles.count}>{parcels.length}</span>}
        </button>
      </div>

      <div
        id="observability-panel"
        role="tabpanel"
        aria-labelledby="observability-tab"
        hidden={activeTab !== 'observability'}
        className={styles.panel}
      >
        <TransparencyRail events={events} history={history} isRunActive={isRunActive} onOpenInspector={onOpenInspector} />
      </div>
      <div
        id="parcels-panel"
        role="tabpanel"
        aria-labelledby="parcels-tab"
        hidden={activeTab !== 'parcels'}
        className={styles.panel}
      >
        {selectedParcel ? (
          <ParcelDetail parcel={selectedParcel} onBack={onBackToResults} />
        ) : (
          <ResultsPanel
            parcels={parcels}
            totalMatching={totalMatching}
            isRunActive={isRunActive}
            events={events}
            onSelectParcel={onSelectParcel}
          />
        )}
      </div>
    </aside>
  )
}
