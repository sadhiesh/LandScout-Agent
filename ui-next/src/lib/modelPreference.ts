/**
 * LLM provider and model selection persistence.
 *
 * Mirrors cachePreference.ts with keys for provider and model.
 */

export const PROVIDER_STORAGE_KEY = 'landscout-next-llm-provider'
export const MODEL_STORAGE_KEY = 'landscout-next-llm-model'

export function readProviderPreference(storage: Pick<Storage, 'getItem'> = localStorage): string | null {
  return storage.getItem(PROVIDER_STORAGE_KEY)
}

export function readModelPreference(storage: Pick<Storage, 'getItem'> = localStorage): string | null {
  return storage.getItem(MODEL_STORAGE_KEY)
}

export function writeProviderPreference(
  value: string,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  storage.setItem(PROVIDER_STORAGE_KEY, value)
}

export function writeModelPreference(
  value: string,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  storage.setItem(MODEL_STORAGE_KEY, value)
}

export function clearModelPreferences(
  storage: Pick<Storage, 'removeItem'> = localStorage,
): void {
  storage.removeItem(PROVIDER_STORAGE_KEY)
  storage.removeItem(MODEL_STORAGE_KEY)
}
