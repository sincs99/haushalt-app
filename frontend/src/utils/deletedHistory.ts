import { ref, shallowRef } from 'vue'
import { useAuthStore } from '../stores/auth'
import { createRequestGuard } from './householdGuard'

/** Offset APIs require refreshing the loaded prefix after deletes/restores shift rows. */
export function createDeletedHistory<T extends { id: string }>(
  fetchPage: (householdId: string, params: { deleted: true; limit: number; offset?: number }) => Promise<T[]>,
  pageSize: number,
) {
  const items = shallowRef<T[]>([])
  const loaded = ref(false)
  const hasMore = ref(false)
  const loading = ref(false)
  const error = ref(false)
  const capture = createRequestGuard()
  let requestedPages = 1
  let revision = 0

  async function fetch(householdId?: string, more = false) {
    const hid = householdId ?? useAuthStore().currentHouseholdId
    if (!hid || (more && (loading.value || !hasMore.value))) return
    const active = capture(hid, 'deleted')
    const requestRevision = revision
    const pages = (loaded.value ? requestedPages : 1) + (more && !error.value ? 1 : 0)
    // Retain the requested range on failure so the visible Retry completes it.
    requestedPages = pages
    loading.value = true
    error.value = false
    try {
      const result = new Map<string, T>()
      let full = false
      for (let index = 0; index < pages; index++) {
        const page = await fetchPage(hid, {
          deleted: true, limit: pageSize, ...(index ? { offset: index * pageSize } : {}),
        })
        if (!active() || revision !== requestRevision) return
        for (const item of page) result.set(item.id, item)
        full = page.length === pageSize
        if (!full) break
      }
      items.value = [...result.values()]
      hasMore.value = full
      loaded.value = true
    } catch (cause) {
      if (active() && revision === requestRevision) error.value = true
      throw cause
    } finally {
      if (active.latest() && revision === requestRevision) loading.value = false
    }
  }

  function reset() {
    revision++
    requestedPages = 1
    items.value = []
    loaded.value = false
    hasMore.value = false
    loading.value = false
    error.value = false
  }

  function drop(id: string) {
    const shouldRefresh = loaded.value || loading.value
    items.value = items.value.filter(item => item.id !== id)
    // Invalidate any response captured before the mutation, including page loads.
    revision++
    loading.value = false
    if (shouldRefresh) void fetch().catch(() => {})
  }

  return { items, loaded, hasMore, loading, error, fetch, loadMore: () => fetch(undefined, true), reset, drop }
}
