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

  function cleanup() {
    if (objectUrl.value) {
      filesRepo.revokeObjectUrl(objectUrl.value)
      objectUrl.value = null
    }
  }

  async function load() {
    cleanup()
    error.value = false

    const hid = householdId.value
    const fid = fileId.value
    if (!hid || !fid) return

    loading.value = true
    try {
      objectUrl.value = await filesRepo.fetchFileAsObjectUrl(hid, fid)
    } catch {
      error.value = true
    } finally {
      loading.value = false
    }
  }

  // Watch für reaktive Änderungen
  watch([householdId, fileId], () => load(), { immediate: true })

  onUnmounted(() => cleanup())

  return { objectUrl, loading, error }
}
