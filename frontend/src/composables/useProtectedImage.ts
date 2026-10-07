import { ref, watch, onUnmounted, type Ref } from 'vue'
import { createOnlineFilesRepository } from '../repositories/filesRepository'

const filesRepo = createOnlineFilesRepository()

export function useProtectedImage(
  householdId: Ref<string | null | undefined>,
  fileId: Ref<string | null | undefined>,
) {
  const objectUrl = ref<string | null>(null)
  const loading = ref(false)
  const error = ref(false)
  let requestVersion = 0
  let disposed = false

  function cleanup() {
    if (objectUrl.value) {
      filesRepo.revokeObjectUrl(objectUrl.value)
      objectUrl.value = null
    }
  }

  async function load() {
    const version = ++requestVersion
    cleanup()
    error.value = false
    loading.value = false

    const hid = householdId.value
    const fid = fileId.value
    if (!hid || !fid) return

    loading.value = true
    try {
      const url = await filesRepo.fetchFileAsObjectUrl(hid, fid)
      if (disposed || version !== requestVersion) {
        filesRepo.revokeObjectUrl(url)
        return
      }
      objectUrl.value = url
    } catch {
      if (!disposed && version === requestVersion) error.value = true
    } finally {
      if (!disposed && version === requestVersion) loading.value = false
    }
  }

  // Watch für reaktive Änderungen
  watch([householdId, fileId], () => load(), { immediate: true, flush: 'sync' })

  onUnmounted(() => {
    disposed = true
    requestVersion++
    cleanup()
  })

  return { objectUrl, loading, error }
}
