/**
 * Accessible candidate picker for selecting parcels from a broad search result.
 * Displays up to 25 candidates with checkboxes, enforces 10-item limit, and submits
 * selected_parcel_ids to /chat.
 */

import { useState } from 'react'
import type { Parcel } from '../results/ShortlistCard'
import styles from './CandidatePicker.module.css'

interface CandidatePickerProps {
  candidates: Parcel[]
  limit: number
  onAnalyze: (selectedIds: string[]) => Promise<void>
  isLoading: boolean
}

export default function CandidatePicker({
  candidates,
  limit,
  onAnalyze,
  isLoading,
}: CandidatePickerProps) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const toggleSelection = (parcelId: string) => {
    const newSelection = new Set(selectedIds)
    if (newSelection.has(parcelId)) {
      newSelection.delete(parcelId)
    } else if (newSelection.size < limit) {
      newSelection.add(parcelId)
    }
    setSelectedIds(newSelection)
  }

  const handleAnalyze = async () => {
    if (selectedIds.size === 0) return
    await onAnalyze(Array.from(selectedIds))
  }

  const formatPrice = (price: number | null | undefined) => {
    if (!price) return 'N/A'
    return `$${(price / 1000).toFixed(0)}k`
  }

  const formatAcres = (acres: number | null | undefined) => {
    if (!acres) return 'N/A'
    return `${acres.toFixed(1)} ac`
  }

  return (
    <div className={styles.container} role="region" aria-label="Candidate parcels">
      <div className={styles.header}>
        <h3 className={styles.title}>
          Select up to {limit} parcels for detailed analysis
        </h3>
        <div className={styles.counter} aria-live="polite">
          {selectedIds.size} of {limit} selected
        </div>
      </div>

      <div className={styles.list}>
        {candidates.map((candidate) => {
          const parcelId = candidate.property_id || String(Math.random())
          const location = candidate.location || {}
          const info = candidate.basic_info || {}
          const isSelected = selectedIds.has(parcelId)
          const isDisabled = !isSelected && selectedIds.size >= limit

          return (
            <label
              key={parcelId}
              className={`${styles.candidateRow} ${isSelected ? styles.selected : ''} ${isDisabled ? styles.disabled : ''}`}
              aria-disabled={isDisabled}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={isDisabled || isLoading}
                onChange={() => toggleSelection(parcelId)}
                aria-label={`Select ${info.title || parcelId}`}
                className={styles.checkbox}
              />
              <div className={styles.details}>
                <div className={styles.titleRow}>
                  <span className={styles.candidateTitle}>
                    {info.title || `Parcel ${parcelId}`}
                  </span>
                  <span className={styles.price}>{formatPrice(info.price)}</span>
                </div>
                <div className={styles.metadata}>
                  <span>{location.city || 'Unknown'}, {location.county || 'TX'}</span>
                  <span className={styles.separator}>•</span>
                  <span>{formatAcres(info.acres)}</span>
                </div>
              </div>
            </label>
          )
        })}
      </div>

      <div className={styles.actions}>
        <button
          className={styles.analyzeButton}
          onClick={handleAnalyze}
          disabled={selectedIds.size === 0 || isLoading}
          aria-label={`Analyze ${selectedIds.size} selected parcel${selectedIds.size !== 1 ? 's' : ''}`}
        >
          {isLoading ? 'Analyzing...' : `Analyze ${selectedIds.size} selected`}
        </button>
      </div>
    </div>
  )
}
