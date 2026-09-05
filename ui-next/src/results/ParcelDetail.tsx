import styles from './ParcelDetail.module.css'
import type { Parcel } from './ShortlistCard'
import { hasSourceData } from './resultSemantics'

interface ParcelDetailProps {
  parcel: Parcel
  onBack: () => void
}

function money(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `$${Math.round(n).toLocaleString()}`
}

function scorePercent(score: number | undefined): number {
  const value = score ?? 0
  return Math.round(Math.min(100, Math.max(0, value <= 1 ? value * 100 : value)))
}

function sourceStatus(value: unknown): 'verified' | 'limited' | 'missing' {
  if (!hasSourceData(value)) return 'missing'
  const status = typeof value === 'object' && value != null
    ? (value as { status?: unknown }).status
    : null
  if (typeof status === 'string' && status !== 'ok' && status !== 'completed') return 'limited'
  return 'verified'
}

export default function ParcelDetail({ parcel, onBack }: ParcelDetailProps) {
  const location = parcel.location || {}
  const info = parcel.basic_info || {}
  const enrichment = parcel.enrichment ?? parcel.enrichments ?? {}
  const cadData = enrichment.cad_parcel
  const cadParcel = cadData?.parcel
  const breakdown = parcel.score_breakdown || {}
  const highlights = breakdown.highlights || []
  const drawbacks = breakdown.drawbacks || []
  const notAssessed = breakdown.not_assessed || []
  const dimensions = breakdown.dimensions || {}
  const considerations = parcel.considerations || []
  const acres = info.acres
  const price = info.price
  const place = [location.city || location.county, location.state].filter(Boolean).join(', ')
  const listingSource = hasSourceData(enrichment.landwatch_detail) ? enrichment.landwatch_detail : info
  const sources = [
    ['Listing', listingSource],
    ['County CAD', enrichment.cad_parcel ?? enrichment.collin_cad],
    ['FEMA flood', enrichment.fema_flood ?? enrichment.flood_fema],
  ] as const

  return (
    <div className={styles.detail}>
      <header className={styles.reportHeader}>
        <button type="button" className={styles.backBtn} onClick={onBack}>
          <span aria-hidden>‹</span> Back to results
        </button>
        <div className={styles.hero}>
          <div>
            <div className={styles.reportLabel}>Parcel investment report</div>
            <h2>{info.title || (acres ? `${acres} acre property` : 'Property report')}</h2>
            <p>{place || 'Location unavailable'}</p>
          </div>
          <div className={styles.scoreBadge}>
            <strong>{scorePercent(parcel.score)}</strong>
            <span>match score</span>
          </div>
        </div>
        <div className={styles.heroStats}>
          <div><span>Price</span><strong>{money(price)}</strong></div>
          <div><span>Acreage</span><strong>{acres ?? '—'}</strong></div>
          <div><span>Price / acre</span><strong>{acres && price ? money(price / acres) : '—'}</strong></div>
        </div>
      </header>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Property summary</h3>
        <dl className={styles.summary}>
          {cadParcel?.parcel_id && (
            <>
              <dt>Parcel ID</dt>
              <dd>{cadParcel.parcel_id}</dd>
            </>
          )}
          {cadParcel?.city && (
            <>
              <dt>Jurisdiction</dt>
              <dd>{cadParcel.city}</dd>
            </>
          )}
          {cadParcel?.valuation?.market != null && (
            <>
              <dt>Appraised Value</dt>
              <dd>{money(cadParcel.valuation.market)}</dd>
            </>
          )}
          {cadParcel?.market_per_acre != null && (
            <>
              <dt>Value per Acre</dt>
              <dd>{money(cadParcel.market_per_acre)}</dd>
            </>
          )}
          {cadParcel?.gis_acres != null && (
            <>
              <dt>GIS Acreage</dt>
              <dd>{Number(cadParcel.gis_acres).toFixed(2)} acres</dd>
            </>
          )}
          {cadParcel?.ag_exempt && (
            <>
              <dt>Agricultural Exemption</dt>
              <dd>Yes</dd>
            </>
          )}
        </dl>
      </section>

      {/* Highlights */}
      {highlights.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Highlights</h3>
          <ul className={styles.itemList}>
            {highlights.map((h, i) => (
              <li key={i} className={styles.highlight}>
                <strong>{h.label}</strong> — {h.detail}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Drawbacks */}
      {drawbacks.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Drawbacks</h3>
          <ul className={styles.itemList}>
            {drawbacks.map((d, i) => (
              <li key={i} className={styles.drawback}>
                <strong>{d.label}</strong> — {d.detail}
              </li>
            ))}
          </ul>
        </section>
      )}

      {parcel.rationale && (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Why this score</h3>
          <p className={styles.rationale}>{parcel.rationale}</p>
        </section>
      )}

      {Object.keys(dimensions).length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Score breakdown</h3>
          <div className={styles.breakdown}>
            {Object.entries(dimensions).map(([dim, dimData]) => (
              <div key={dim} className={styles.dim}>
                <div className={styles.dimHeader}>
                  <span className={styles.dimLabel}>{dim.replace(/_/g, ' ')}</span>
                  <span className={styles.dimScore}>{Math.round(dimData.raw_score * 100)}</span>
                </div>
                <div className={styles.barTrack}>
                  <div
                    className={styles.barFill}
                    style={{ width: `${Math.min(100, Math.max(0, dimData.raw_score * 100))}%` }}
                  />
                </div>
                {dimData.explanation && (
                  <div className={styles.dimExpl}>{dimData.explanation}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Data sources</h3>
        <div className={styles.sources}>
          {sources.map(([label, value]) => {
            const status = sourceStatus(value)
            return (
              <div key={label} className={styles.sourceRow}>
                <span>{label}</span>
                <span className={`${styles.sourceStatus} ${styles[status]}`}>
                  {status === 'verified' ? 'Available' : status === 'limited' ? 'Limited' : 'Not available'}
                </span>
              </div>
            )
          })}
        </div>
      </section>

      {notAssessed.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Not assessed</h3>
          <ul className={styles.itemList}>
            {notAssessed.map((na, i) => (
              <li key={i} className={styles.notAssessed}>
                <strong>{na.label}</strong> — {na.reason}
              </li>
            ))}
          </ul>
        </section>
      )}

      {considerations.length > 0 && (
        <section className={`${styles.section} ${styles.considerationsSection}`}>
          <h3 className={styles.sectionTitle}>Model-generated considerations</h3>
          <p className={styles.considerationsNote}>
            These are model-generated suggestions, not retrieved facts. Verify independently.
          </p>
          <ul className={styles.itemList}>
            {considerations.map((c, i) => (
              <li key={i} className={styles.consideration}>
                {c}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
