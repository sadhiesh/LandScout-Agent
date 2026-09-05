import type { Parcel } from './ShortlistCard'

export type SortMode = 'score' | 'price' | 'acres'

export function sortParcels(parcels: Parcel[], sortMode: SortMode): Parcel[] {
  const copy = [...parcels]
  if (sortMode === 'price') {
    return copy.sort((a, b) => (a.basic_info?.price ?? Infinity) - (b.basic_info?.price ?? Infinity))
  }
  if (sortMode === 'acres') {
    return copy.sort((a, b) => (b.basic_info?.acres ?? 0) - (a.basic_info?.acres ?? 0))
  }
  return copy.sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
}

export function topScoringParcel(parcels: Parcel[]): Parcel | null {
  return parcels.reduce<Parcel | null>((top, parcel) => {
    if (parcel.score == null || !Number.isFinite(parcel.score)) return top
    return top == null || parcel.score > (top.score ?? -Infinity) ? parcel : top
  }, null)
}

export function hasSourceData(value: unknown): boolean {
  if (value == null) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  if (typeof value === 'string') return value.trim().length > 0
  return true
}
