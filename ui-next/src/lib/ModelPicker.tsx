/**
 * LLM provider and model picker.
 *
 * Two dropdowns: provider, then model (filtered to that provider).
 * Unavailable providers are disabled with a hint.
 */

import { useEffect, useState } from 'react'
import { useModelCatalog } from './useModelCatalog'
import {
  readProviderPreference,
  readModelPreference,
  writeProviderPreference,
  writeModelPreference,
} from './modelPreference'
import styles from './ModelPicker.module.css'

interface ModelPickerProps {
  onSelectionChange: (provider: string | null, model: string | null) => void
}

export default function ModelPicker({ onSelectionChange }: ModelPickerProps) {
  const { catalog, loading, error } = useModelCatalog()
  const [provider, setProvider] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)

  // Initialize from localStorage or catalog defaults
  useEffect(() => {
    if (!catalog) return

    const savedProvider = readProviderPreference()
    const savedModel = readModelPreference()

    // Use saved if valid, otherwise catalog defaults
    const initialProvider =
      savedProvider && catalog.providers[savedProvider]?.available
        ? savedProvider
        : catalog.default_provider

    const initialModel =
      savedModel && catalog.providers[initialProvider]?.models.some((m) => m.id === savedModel)
        ? savedModel
        : catalog.default_model

    setProvider(initialProvider)
    setModel(initialModel)
    onSelectionChange(initialProvider, initialModel)
  }, [catalog, onSelectionChange])

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider)
    writeProviderPreference(newProvider)

    // Reset model to first available for new provider
    const providerEntry = catalog?.providers[newProvider]
    const newModel = providerEntry?.models[0]?.id || null
    setModel(newModel)
    if (newModel) {
      writeModelPreference(newModel)
    }

    onSelectionChange(newProvider, newModel)
  }

  const handleModelChange = (newModel: string) => {
    setModel(newModel)
    writeModelPreference(newModel)
    onSelectionChange(provider, newModel)
  }

  if (loading) {
    return <div className={styles.loading}>Loading models…</div>
  }

  if (error) {
    return <div className={styles.error}>Model catalog unavailable</div>
  }

  if (!catalog || !provider || !model) {
    return null
  }

  const providerEntry = catalog.providers[provider]
  const availableModels = providerEntry?.models || []

  return (
    <div className={styles.picker}>
      <label className={styles.label}>
        <span className={styles.labelText}>Provider</span>
        <select
          value={provider}
          onChange={(e) => handleProviderChange(e.target.value)}
          className={styles.select}
          aria-label="LLM provider"
        >
          {Object.entries(catalog.providers).map(([id, entry]) => (
            <option key={id} value={id} disabled={!entry.available}>
              {entry.label} {!entry.available && '(key not configured)'}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.label}>
        <span className={styles.labelText}>Model</span>
        <select
          value={model}
          onChange={(e) => handleModelChange(e.target.value)}
          className={styles.select}
          aria-label="LLM model"
        >
          {availableModels.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label} {m.reasoning && '⚡'}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
