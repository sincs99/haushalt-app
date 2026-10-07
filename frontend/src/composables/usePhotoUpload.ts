import { onUnmounted, ref, watch, type Ref } from 'vue'
import { createOnlineFilesRepository } from '../repositories/filesRepository'
import { ImageTooLargeError, MAX_UPLOAD_BYTES, prepareImageForUpload } from '../utils/imageUpload'
import type { StoredFile } from '../types'

/** Keep upload, association and cleanup bound to the entity selected at the start. */
export function usePhotoUpload(options: {
  householdId: Ref<string | null>
  entityId: Ref<string>
  fileId: Ref<string | null>
  update: (householdId: string, entityId: string, fileId: string) => Promise<unknown>
}) {
  const repo = createOnlineFilesRepository()
  const uploading = ref(false)
  let version = 0
  let disposed = false
  watch([options.householdId, options.entityId], () => version++, { flush: 'sync' })
  onUnmounted(() => { disposed = true; version++ })

  async function upload(file: File): Promise<boolean> {
    const householdId = options.householdId.value
    if (!householdId || uploading.value) return false
    const entityId = options.entityId.value
    const oldFileId = options.fileId.value
    const startedAt = version
    const active = () => !disposed && version === startedAt
    let uploaded: StoredFile | null = null
    let associated = false
    uploading.value = true

    async function cleanup(fileId: string) {
      try { await repo.deleteFile(householdId!, fileId) } catch { /* best effort, FILE_IN_USE is safe */ }
    }

    try {
      const prepared = await prepareImageForUpload(file)
      if (!active()) return false
      if (prepared.size > MAX_UPLOAD_BYTES) throw new ImageTooLargeError()
      uploaded = await repo.uploadFile(householdId, prepared)
      if (!active()) return false
      await options.update(householdId, entityId, uploaded.id)
      associated = true
      if (oldFileId) await cleanup(oldFileId)
      return active()
    } catch (error) {
      if (active()) throw error
      return false
    } finally {
      if (uploaded && !associated) await cleanup(uploaded.id)
      uploading.value = false
    }
  }

  return { uploading, upload }
}
