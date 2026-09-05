export const SKIP_CACHE_STORAGE_KEY = 'landscout-next-skip-cache'
const LEGACY_SKIP_CACHE_STORAGE_KEY = 'landscout_skip_cache'

export function readSkipCachePreference(storage: Pick<Storage, 'getItem' | 'setItem'> = localStorage): boolean {
  const current = storage.getItem(SKIP_CACHE_STORAGE_KEY)
  if (current != null) return current === 'true'

  const legacy = storage.getItem(LEGACY_SKIP_CACHE_STORAGE_KEY)
  if (legacy != null) {
    storage.setItem(SKIP_CACHE_STORAGE_KEY, legacy)
    return legacy === 'true'
  }
  return false
}

export function writeSkipCachePreference(
  value: boolean,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  storage.setItem(SKIP_CACHE_STORAGE_KEY, String(value))
}
