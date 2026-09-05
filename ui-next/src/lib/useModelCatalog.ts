/**
 * Fetch and cache the LLM model catalog from /config/models.
 */

import { useEffect, useState } from 'react'

export interface ModelEntry {
  id: string
  label: string
  reasoning: boolean
}

export interface ProviderEntry {
  label: string
  available: boolean
  models: ModelEntry[]
}

export interface ModelCatalog {
  default_provider: string
  default_model: string
  providers: Record<string, ProviderEntry>
}

export function useModelCatalog(): {
  catalog: ModelCatalog | null
  loading: boolean
  error: string | null
} {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true

    fetch('/config/models')
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to fetch catalog: ${res.statusText}`)
        return res.json()
      })
      .then((data) => {
        if (mounted) {
          setCatalog(data)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Unknown error')
          setLoading(false)
        }
      })

    return () => {
      mounted = false
    }
  }, [])

  return { catalog, loading, error }
}
