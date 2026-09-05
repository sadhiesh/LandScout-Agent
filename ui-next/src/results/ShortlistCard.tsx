import styles from './ShortlistCard.module.css'

export interface DimensionData {
  dimension: string
  raw_score: number
  weight: number
  weighted_score: number
  explanation: string
}

export interface Parcel {
  property_id?: string
  location?: any
  basic_info?: any
  score?: number
  score_breakdown?: {
    dimensions?: Record<string, DimensionData>
    highlights?: any[]
    drawbacks?: any[]
    not_assessed?: any[]
  }
  rationale?: string
  enrichment?: Record<string, any>
  enrichments?: Record<string, any>
  considerations?: string[]
}

interface ShortlistCardProps {
  parcel: Parcel
  topPick?: boolean
  rank?: number
  variant?: 'inline' | 'list'
  onSelect: () => void
}

type LandMotif = 'farm' | 'forest' | 'generic' | 'location' | 'water'

function money(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `$${Math.round(n).toLocaleString()}`
}

function landMotifFor(propertyTypes: unknown): LandMotif {
  if (!Array.isArray(propertyTypes)) return 'generic'

  const types = propertyTypes.filter((type): type is string => typeof type === 'string').join(' ').toLowerCase()
  if (/(water|lake|ocean|river|beach)/.test(types)) return 'water'
  if (/(farm|ranch|agricultur|horse)/.test(types)) return 'farm'
  if (/(timber|forest|wood|hunting)/.test(types)) return 'forest'
  if (/(home|house|commercial|development)/.test(types)) return 'location'
  return 'generic'
}

function LandFallback({ motif }: { motif: LandMotif }) {
  return (
    <svg
      className={styles.landscape}
      viewBox="0 0 240 72"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <circle className={styles.motifSun} cx="198" cy="18" r="8" />

      {motif === 'water' && (
        <>
          <path className={styles.motifBack} d="M0 48 43 22l31 25 32-19 40 30H0Z" />
          <path className={styles.motifFront} d="M0 52c28-8 51 8 79 0s51 8 79 0 54 7 82-1v21H0Z" />
          <path className={styles.motifLine} d="M17 61c16-5 28 5 44 0s28 5 44 0 28 5 44 0 28 5 44 0" />
        </>
      )}

      {motif === 'farm' && (
        <>
          <path className={styles.motifBack} d="M0 49c42-20 76-18 116 2 41 20 79 13 124-9v30H0Z" />
          <path className={styles.motifFront} d="M0 61c62-18 122-15 178 3 21 7 42 6 62 2v6H0Z" />
          <path className={styles.motifAccent} d="M67 38 84 25l17 13v25H67Z" />
          <path className={styles.motifCutout} d="M79 47h10v16H79z" />
          <path className={styles.motifLine} d="m111 55 18 17m4-23 26 23m-5-29 42 29" />
        </>
      )}

      {motif === 'forest' && (
        <>
          <path className={styles.motifBack} d="M0 55 48 30l34 25 41-34 53 44 24-19 40 18v8H0Z" />
          <path className={styles.motifFront} d="M0 64c55-13 113-13 166 1 25 7 49 7 74 1v6H0Z" />
          <path className={styles.motifAccent} d="m34 55 10-21 10 21h-6v12h-8V55Zm136 1 12-27 12 27h-8v12h-8V56Z" />
        </>
      )}

      {motif === 'location' && (
        <>
          <path className={styles.motifBack} d="M0 57c41-25 77-24 111-3 39 24 80 17 129-8v26H0Z" />
          <path className={styles.motifFront} d="M0 65c56-13 112-12 168 1 25 6 49 6 72 1v5H0Z" />
          <path
            className={styles.motifAccent}
            fillRule="evenodd"
            d="M117 15c-10 0-18 8-18 18 0 13 18 29 18 29s18-16 18-29c0-10-8-18-18-18Zm0 24a6 6 0 1 1 0-12 6 6 0 0 1 0 12Z"
          />
        </>
      )}

      {motif === 'generic' && (
        <>
          <path className={styles.motifBack} d="M0 57 47 28l35 24 42-35 55 47 24-20 37 17v11H0Z" />
          <path className={styles.motifFront} d="M0 62c46-18 94-16 139 2 34 13 67 12 101 2v6H0Z" />
          <path className={styles.motifAccent} d="m184 54 10-22 10 22h-6v13h-8V54Z" />
        </>
      )}
    </svg>
  )
}

export default function ShortlistCard({ parcel, topPick = false, rank, variant = 'list', onSelect }: ShortlistCardProps) {
  const location = parcel.location || {}
  const info = parcel.basic_info || {}
  // Canonical field is `enrichment` (docs/agent-contracts.md); fall back to legacy `enrichments`.
  const enrichment = parcel.enrichment ?? parcel.enrichments ?? {}
  const cadData = enrichment.cad_parcel ?? enrichment.collin_cad
  const breakdown = parcel.score_breakdown || {}
  const topHighlight = (breakdown.highlights || [])[0]
  const hasCad = cadData && cadData.parcel
  const acres = info.acres || 0
  const price = info.price || 0
  const perAcre = acres > 0 ? price / acres : null
  const place = [location.city || location.county, location.state].filter(Boolean).join(', ')
  const imageUrl = typeof info.image_url === 'string' && info.image_url.trim() ? info.image_url : null
  const landMotif = landMotifFor(info.property_types)
  const scorePct = Math.round(
    Math.min(100, Math.max(0, (parcel.score || 0) * (parcel.score && parcel.score <= 1 ? 100 : 1))),
  )

  return (
    <button
      type="button"
      className={`${styles.card} ${styles[variant]} ${topPick ? styles.topPick : ''}`}
      onClick={onSelect}
      aria-label={`Open details for ${info.title || place || 'parcel'}`}
    >
      <div
        className={`${styles.thumb} ${imageUrl ? styles.listingImage : styles.landFallback}`}
        style={{
          backgroundImage: imageUrl ? `url(${imageUrl}), var(--image-fallback)` : undefined,
        }}
      >
        {!imageUrl && <LandFallback motif={landMotif} />}
        {rank != null && <span className={styles.rank}>{rank}</span>}
        {topPick && <span className={styles.flag}>Top pick</span>}
      </div>

      <div className={styles.body}>
        <div className={styles.topRow}>
          <div>
            <div className={styles.name}>{acres ? `${acres.toLocaleString()} acres` : info.title || 'Untitled property'}</div>
            <div className={styles.location}>{place || 'Location unavailable'}</div>
          </div>
          <div className={styles.priceBlock}>
            <div className={styles.price}>{money(price)}</div>
            {perAcre != null && <div className={styles.priceSub}>{money(perAcre)}/acre</div>}
          </div>
        </div>

        <div className={styles.scoreRow}>
          <span>Match score</span>
          <strong>{scorePct}/100</strong>
        </div>

        <div className={styles.tags}>
          {info.property_types && Array.isArray(info.property_types) && info.property_types.length > 0 && (
            <span className={styles.tag}>{info.property_types[0]}</span>
          )}
          {hasCad && <span className={`${styles.tag} ${styles.verified}`}>CAD verified</span>}
          {info.zoning && <span className={styles.tag}>{info.zoning}</span>}
        </div>

        {topHighlight && (
          <div className={styles.quickHighlight}>
            <strong>{topHighlight.label}:</strong> {topHighlight.detail}
          </div>
        )}
        <span className={styles.openHint}>View full report <span aria-hidden>›</span></span>
      </div>
    </button>
  )
}
