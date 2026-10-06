<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { MAX_DOCUMENT_FILES, useDocumentsStore } from '../stores/documents'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { createOnlineFilesRepository } from '../repositories/filesRepository'
import { translateApiError } from '../utils/apiErrors'
import { formatDate } from '../utils/dates'
import { formatBytes, getExpiryStatus, isPreviewable } from '../utils/documents'
import { DOCUMENT_CATEGORIES, type DocumentCategory, type DocumentItem, type StoredFile } from '../types'

import PageHeader from '../components/ui/PageHeader.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BasePillTabs from '../components/ui/BasePillTabs.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseSpinner from '../components/ui/BaseSpinner.vue'
import {
  PhPlus, PhTrash, PhFolderOpen, PhFilePdf, PhFileImage, PhDownloadSimple, PhEye, PhMagnifyingGlass,
  PhCamera, PhCaretUp, PhCaretDown, PhCaretLeft, PhCaretRight, PhX,
} from '@phosphor-icons/vue'

const { t } = useI18n()
const { showToast } = useToast()
const socket = useSocket()
const authStore = useAuthStore()
const store = useDocumentsStore()
const filesRepo = createOnlineFilesRepository()

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10 MB pro Seite, wie Backend
const ACCEPTED_TYPES = 'application/pdf,image/jpeg,image/png,image/webp'

// ── Filter & Suche ──
const categoryTabs = computed(() => [
  { key: 'all', label: t('documents.categories.all') },
  ...DOCUMENT_CATEGORIES.map((c) => ({ key: c, label: t(`documents.categories.${c}`) })),
])
const activeTab = computed(() => store.category ?? 'all')

function handleTabChange(key: string) {
  store.setCategory(key === 'all' ? null : (key as DocumentCategory)).catch(() => {
    showToast(t('documents.loadError'), 'error')
  })
}

const searchInput = ref(store.query)
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(searchInput, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    store.setQuery(value).catch(() => showToast(t('documents.loadError'), 'error'))
  }, 300)
})

function handleLoadMore() {
  store.loadMore().catch(() => showToast(t('documents.loadError'), 'error'))
}

const isFiltered = computed(() => !!store.category || !!store.query.trim())

const storageLabel = computed(() => {
  if (!store.storage) return ''
  return t('documents.storageUsage', {
    used: formatBytes(store.storage.used_bytes),
    quota: formatBytes(store.storage.quota_bytes),
  })
})

// ── Ablauf-Badge ──
function expiryBadge(doc: DocumentItem): { cls: string; label: string } | null {
  const status = getExpiryStatus(doc.expiry_date)
  if (!status || status.state === 'ok') return null
  if (status.state === 'expired') {
    return { cls: 'expiry-badge--expired', label: t('documents.expired') }
  }
  return {
    cls: 'expiry-badge--soon',
    label: status.days === 0 ? t('documents.expiresToday') : t('documents.expiresInDays', status.days),
  }
}

function isPdf(mime: string) {
  return mime === 'application/pdf'
}

// ── Formular-Dialog (Upload + Bearbeiten) ──
const showFormDialog = ref(false)
// Über die ID referenzieren: Socket-/Server-Updates ersetzen das Item-Objekt im Store
const editingDocId = ref<string | null>(null)
const editingDoc = computed(() => store.items.find((i) => i.id === editingDocId.value) ?? null)
const pendingFiles = ref<File[]>([])
const formTitle = ref('')
const formCategory = ref<DocumentCategory>('other')
const formNotes = ref('')
const formDocumentDate = ref('')
const formExpiryDate = ref('')
const formLoading = ref(false)
const pagesBusy = ref(false)
const uploadProgress = ref<{ current: number; total: number } | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const cameraInputRef = ref<HTMLInputElement | null>(null)

const canSave = computed(() =>
  editingDoc.value ? !!formTitle.value.trim() : pendingFiles.value.length > 0,
)

const pageCount = computed(() =>
  editingDoc.value ? editingDoc.value.files.length : pendingFiles.value.length,
)

const progressLabel = computed(() =>
  uploadProgress.value
    ? t('documents.uploadingPage', { current: uploadProgress.value.current, total: uploadProgress.value.total })
    : '',
)

function resetForm() {
  pendingFiles.value = []
  formTitle.value = ''
  formCategory.value = store.category ?? 'other'
  formNotes.value = ''
  formDocumentDate.value = ''
  formExpiryDate.value = ''
  uploadProgress.value = null
}

function openUploadDialog() {
  editingDocId.value = null
  resetForm()
  showFormDialog.value = true
}

function openEditDialog(doc: DocumentItem) {
  editingDocId.value = doc.id
  pendingFiles.value = []
  formTitle.value = doc.title
  formCategory.value = doc.category
  formNotes.value = doc.notes ?? ''
  formDocumentDate.value = doc.document_date ?? ''
  formExpiryDate.value = doc.expiry_date ?? ''
  uploadProgress.value = null
  showFormDialog.value = true
}

function closeFormDialog() {
  if (formLoading.value || pagesBusy.value) return
  showFormDialog.value = false
  editingDocId.value = null
}

function onProgress(current: number, total: number) {
  uploadProgress.value = { current, total }
}

/** Prüft ausgewählte Dateien clientseitig (Grösse, Seitenlimit); Backend prüft zusätzlich */
function acceptFiles(selected: File[]): File[] {
  const tooLarge = selected.filter((f) => f.size > MAX_FILE_SIZE)
  if (tooLarge.length > 0) {
    showToast(t('files.FILE_TOO_LARGE'), 'error')
  }
  const valid = selected.filter((f) => f.size <= MAX_FILE_SIZE)
  const free = MAX_DOCUMENT_FILES - pageCount.value
  if (valid.length > free) {
    showToast(t('documents.tooManyPages', { max: MAX_DOCUMENT_FILES }), 'error')
  }
  return valid.slice(0, Math.max(0, free))
}

async function handleFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = acceptFiles(Array.from(input.files ?? []))
  // Reset damit dieselbe Datei erneut gewählt werden kann
  input.value = ''
  if (selected.length === 0) return

  if (!editingDoc.value) {
    pendingFiles.value = [...pendingFiles.value, ...selected]
    // Titel aus erstem Dateinamen vorschlagen, falls noch leer
    if (!formTitle.value.trim()) {
      formTitle.value = selected[0].name.replace(/\.[^.]+$/, '').slice(0, 150)
    }
    return
  }

  // Bestehendes Dokument: Seiten direkt hochladen und anhängen
  pagesBusy.value = true
  try {
    await store.addPages(editingDoc.value.id, selected, onProgress)
  } catch (error) {
    showToast(translateApiError(error), 'error')
  } finally {
    pagesBusy.value = false
    uploadProgress.value = null
  }
}

function movePendingFile(index: number, direction: -1 | 1) {
  const files = [...pendingFiles.value]
  const target = index + direction
  if (target < 0 || target >= files.length) return
  ;[files[index], files[target]] = [files[target], files[index]]
  pendingFiles.value = files
}

function removePendingFile(index: number) {
  pendingFiles.value = pendingFiles.value.filter((_, i) => i !== index)
}

async function moveStoredPage(fileId: string, direction: -1 | 1) {
  if (!editingDoc.value) return
  try {
    await store.movePage(editingDoc.value.id, fileId, direction)
  } catch (error) {
    showToast(translateApiError(error), 'error')
  }
}

async function removeStoredPage(file: StoredFile) {
  const doc = editingDoc.value
  if (!doc || doc.files.length <= 1) return
  if (!confirm(t('documents.removePageConfirm', { name: file.original_name }))) return

  pagesBusy.value = true
  try {
    await store.removePage(doc.id, file.id)
  } catch (error) {
    showToast(translateApiError(error), 'error')
  } finally {
    pagesBusy.value = false
  }
}

function formMeta() {
  return {
    title: formTitle.value.trim(),
    category: formCategory.value,
    notes: formNotes.value.trim() || null,
    document_date: formDocumentDate.value || null,
    expiry_date: formExpiryDate.value || null,
  }
}

async function handleSave() {
  if (!canSave.value || formLoading.value || pagesBusy.value) return

  formLoading.value = true
  try {
    if (editingDoc.value) {
      await store.updateDocument(editingDoc.value.id, formMeta())
    } else {
      await store.uploadDocument(pendingFiles.value, formMeta(), onProgress)
      showToast(t('documents.uploadSuccess'), 'success')
    }
    formLoading.value = false
    closeFormDialog()
  } catch (error) {
    showToast(translateApiError(error), 'error')
  } finally {
    formLoading.value = false
    uploadProgress.value = null
  }
}

async function handleDelete() {
  const doc = editingDoc.value
  if (!doc) return
  if (!confirm(t('documents.deleteConfirm', { title: doc.title, n: doc.files.length }, doc.files.length))) return

  closeFormDialog()
  try {
    await store.deleteDocument(doc.id)
  } catch {
    showToast(t('documents.deleteError'), 'error')
  }
}

// ── Download & Vorschau (Blob mit JWT, siehe useProtectedImage) ──
const showPreview = ref(false)
const previewDocId = ref<string | null>(null)
const previewDoc = computed(() => store.items.find((i) => i.id === previewDocId.value) ?? null)
const previewIndex = ref(0)
const previewFile = computed(() => previewDoc.value?.files[previewIndex.value] ?? null)
const previewUrl = ref<string | null>(null)
const previewLoading = ref(false)

async function fetchBlob(file: StoredFile): Promise<Blob | null> {
  const householdId = authStore.currentHouseholdId
  if (!householdId) return null
  return filesRepo.fetchFileBlob(householdId, file.id)
}

async function handleDownload(file: StoredFile) {
  try {
    const blob = await fetchBlob(file)
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.original_name
    document.body.appendChild(link)
    link.click()
    link.remove()
    // Kurz warten, damit der Browser den Download starten kann
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  } catch {
    showToast(t('documents.downloadError'), 'error')
  }
}

function revokePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

async function loadPreview() {
  revokePreview()
  const file = previewFile.value
  if (!file) return
  if (!isPreviewable(file.mime_type)) return

  previewLoading.value = true
  try {
    const blob = await fetchBlob(file)
    // Dialog könnte inzwischen geschlossen oder auf eine andere Seite gewechselt sein
    if (blob && showPreview.value && previewFile.value?.id === file.id) {
      previewUrl.value = URL.createObjectURL(blob)
    }
  } catch {
    showToast(t('documents.downloadError'), 'error')
  } finally {
    previewLoading.value = false
  }
}

function openPreview(doc: DocumentItem, index = 0) {
  previewDocId.value = doc.id
  previewIndex.value = index
  showPreview.value = true
  loadPreview()
}

function showPreviewPage(index: number) {
  if (!previewDoc.value || index < 0 || index >= previewDoc.value.files.length) return
  previewIndex.value = index
  loadPreview()
}

function closePreview() {
  showPreview.value = false
  previewDocId.value = null
  revokePreview()
}

// Dokument wurde gelöscht oder Seite entfernt, während die Vorschau offen ist
watch(previewFile, (file, old) => {
  if (!showPreview.value) return
  if (!previewDoc.value) {
    closePreview()
  } else if (!file) {
    showPreviewPage(previewDoc.value.files.length - 1)
  } else if (file.id !== old?.id) {
    loadPreview()
  }
})

// ── Socket Events ──
function refreshStorage() {
  store.fetchStorage().catch(() => {})
}

function loadAll() {
  store.fetchDocuments().catch(() => showToast(t('documents.loadError'), 'error'))
  refreshStorage()
}

function handleReconnect() {
  loadAll()
}

// Haushaltswechsel: Liste neu laden
watch(() => authStore.currentHouseholdId, () => {
  store.reset()
  loadAll()
})

// ── Lifecycle ──
onMounted(() => {
  loadAll()

  socket.on('document_created', store.handleDocumentCreated)
  socket.on('document_updated', store.handleDocumentUpdated)
  socket.on('document_deleted', store.handleDocumentDeleted)
  socket.on('document_created', refreshStorage)
  socket.on('document_updated', refreshStorage)
  socket.on('document_deleted', refreshStorage)
  socket.onReconnect(handleReconnect)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  revokePreview()
  socket.off('document_created', store.handleDocumentCreated)
  socket.off('document_updated', store.handleDocumentUpdated)
  socket.off('document_deleted', store.handleDocumentDeleted)
  socket.off('document_created', refreshStorage)
  socket.off('document_updated', refreshStorage)
  socket.off('document_deleted', refreshStorage)
  socket.offReconnect(handleReconnect)
})
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('documents.title')" :subtitle="storageLabel">
      <template #actions>
        <BaseButton variant="primary" size="sm" @click="openUploadDialog">
          <PhPlus :size="16" weight="bold" />
          {{ $t('documents.upload') }}
        </BaseButton>
      </template>
    </PageHeader>

    <!-- Suche -->
    <div class="search">
      <PhMagnifyingGlass :size="18" class="search__icon" aria-hidden="true" />
      <BaseInput
        v-model="searchInput"
        type="search"
        :placeholder="$t('documents.searchPlaceholder')"
        :aria-label="$t('common.search')"
        autocomplete="off"
        enterkeyhint="search"
      />
    </div>

    <!-- Kategorie-Filter -->
    <BasePillTabs
      class="category-tabs"
      :tabs="categoryTabs"
      :model-value="activeTab"
      @update:model-value="handleTabChange"
    />

    <!-- Loading -->
    <div v-if="store.loading && store.items.length === 0" class="skeleton-list">
      <BaseSkeleton v-for="i in 3" :key="i" width="100%" height="72px" />
    </div>

    <!-- Empty State -->
    <BaseEmptyState
      v-else-if="store.items.length === 0"
      :icon="PhFolderOpen"
      :title="isFiltered ? $t('common.noResults') : $t('documents.emptyTitle')"
      :subtitle="isFiltered ? $t('documents.emptyFilteredSubtitle') : $t('documents.emptySubtitle')"
    />

    <!-- Liste -->
    <ul v-else class="doc-list">
      <li
        v-for="doc in store.items"
        :key="doc.id"
        class="doc-card"
        tabindex="0"
        @click="openEditDialog(doc)"
        @keydown.enter="openEditDialog(doc)"
      >
        <span class="doc-card__icon" aria-hidden="true">
          <PhFilePdf v-if="isPdf(doc.files[0].mime_type)" :size="24" />
          <PhFileImage v-else :size="24" />
        </span>
        <div class="doc-card__body">
          <span class="doc-card__title">{{ doc.title }}</span>
          <div class="doc-card__meta">
            <span class="category-chip">{{ $t(`documents.categories.${doc.category}`) }}</span>
            <span v-if="doc.files.length > 1" class="doc-card__date">
              {{ $t('documents.pageCount', doc.files.length) }}
            </span>
            <span v-if="doc.document_date" class="doc-card__date">{{ formatDate(doc.document_date) }}</span>
            <span
              v-if="expiryBadge(doc)"
              class="expiry-badge"
              :class="expiryBadge(doc)!.cls"
            >{{ expiryBadge(doc)!.label }}</span>
            <span v-else-if="doc.expiry_date" class="doc-card__date">
              {{ $t('documents.validUntil', { date: formatDate(doc.expiry_date) }) }}
            </span>
          </div>
        </div>
        <div class="doc-card__actions">
          <button
            v-if="isPreviewable(doc.files[0].mime_type)"
            class="icon-btn tap-target"
            :aria-label="$t('documents.preview')"
            @click.stop="openPreview(doc)"
          >
            <PhEye :size="18" />
          </button>
          <!-- Mehrseitige Dokumente: Download pro Seite im Dialog/Vorschau -->
          <button
            v-if="doc.files.length === 1"
            class="icon-btn tap-target"
            :aria-label="$t('documents.download')"
            @click.stop="handleDownload(doc.files[0])"
          >
            <PhDownloadSimple :size="18" />
          </button>
        </div>
      </li>
    </ul>

    <div v-if="store.hasMore" class="load-more">
      <BaseButton variant="secondary" size="sm" :loading="store.loadingMore" @click="handleLoadMore">
        {{ $t('documents.loadMore') }}
      </BaseButton>
    </div>

    <!-- Upload-/Bearbeiten-Dialog -->
    <BaseDialog
      :open="showFormDialog"
      :title="editingDoc ? $t('documents.editTitle') : $t('documents.uploadTitle')"
      @close="closeFormDialog"
    >
      <form class="doc-form" @submit.prevent="handleSave">
        <!-- Seiten -->
        <div class="form-field">
          <span class="form-field__label">
            {{ $t('documents.pagesLabel') }}
            <span v-if="pageCount > 0" class="form-field__count">({{ pageCount }})</span>
          </span>

          <!-- Neues Dokument: lokal gewählte Dateien -->
          <ol v-if="!editingDoc && pendingFiles.length > 0" class="page-list">
            <li v-for="(file, index) in pendingFiles" :key="`${file.name}-${file.lastModified}-${index}`" class="page-row">
              <span class="page-row__num">{{ index + 1 }}</span>
              <span class="page-row__name">{{ file.name }}<small>{{ formatBytes(file.size) }}</small></span>
              <button type="button" class="icon-btn tap-target" :disabled="index === 0" :aria-label="$t('documents.moveUp')" @click="movePendingFile(index, -1)">
                <PhCaretUp :size="16" />
              </button>
              <button type="button" class="icon-btn tap-target" :disabled="index === pendingFiles.length - 1" :aria-label="$t('documents.moveDown')" @click="movePendingFile(index, 1)">
                <PhCaretDown :size="16" />
              </button>
              <button type="button" class="icon-btn tap-target" :aria-label="$t('documents.removePage')" @click="removePendingFile(index)">
                <PhX :size="16" />
              </button>
            </li>
          </ol>

          <!-- Bestehendes Dokument: gespeicherte Seiten -->
          <ol v-else-if="editingDoc" class="page-list">
            <li v-for="(file, index) in editingDoc.files" :key="file.id" class="page-row">
              <span class="page-row__num">{{ index + 1 }}</span>
              <button
                type="button"
                class="page-row__name page-row__name--link tap-target"
                :disabled="!isPreviewable(file.mime_type)"
                @click="openPreview(editingDoc, index)"
              >{{ file.original_name }}<small>{{ formatBytes(file.size_bytes) }}</small></button>
              <button type="button" class="icon-btn tap-target" :aria-label="$t('documents.download')" @click="handleDownload(file)">
                <PhDownloadSimple :size="16" />
              </button>
              <button type="button" class="icon-btn tap-target" :disabled="index === 0 || pagesBusy" :aria-label="$t('documents.moveUp')" @click="moveStoredPage(file.id, -1)">
                <PhCaretUp :size="16" />
              </button>
              <button type="button" class="icon-btn tap-target" :disabled="index === editingDoc.files.length - 1 || pagesBusy" :aria-label="$t('documents.moveDown')" @click="moveStoredPage(file.id, 1)">
                <PhCaretDown :size="16" />
              </button>
              <button
                type="button"
                class="icon-btn tap-target"
                :disabled="editingDoc.files.length <= 1 || pagesBusy"
                :aria-label="$t('documents.removePage')"
                @click="removeStoredPage(file)"
              >
                <PhX :size="16" />
              </button>
            </li>
          </ol>

          <input ref="fileInputRef" type="file" class="file-input" :accept="ACCEPTED_TYPES" multiple @change="handleFilesSelected" />
          <!-- Kamera: auf dem Handy Seite für Seite abfotografieren -->
          <input ref="cameraInputRef" type="file" class="file-input" accept="image/*" capture="environment" @change="handleFilesSelected" />
          <div class="page-actions">
            <BaseButton
              variant="secondary"
              size="sm"
              :disabled="pagesBusy || formLoading || pageCount >= MAX_DOCUMENT_FILES"
              @click="fileInputRef?.click()"
            >
              <PhPlus :size="14" weight="bold" />
              {{ pageCount > 0 ? $t('documents.addPages') : $t('documents.chooseFiles') }}
            </BaseButton>
            <BaseButton
              variant="secondary"
              size="sm"
              :disabled="pagesBusy || formLoading || pageCount >= MAX_DOCUMENT_FILES"
              @click="cameraInputRef?.click()"
            >
              <PhCamera :size="14" />
              {{ $t('documents.takePhoto') }}
            </BaseButton>
          </div>
          <span class="form-field__hint">{{ progressLabel || $t('documents.fileHint', { max: MAX_DOCUMENT_FILES }) }}</span>
        </div>

        <BaseInput
          v-model="formTitle"
          :label="$t('documents.titleLabel')"
          :placeholder="$t('documents.titlePlaceholder')"
          maxlength="150"
          autocomplete="off"
        />

        <div class="form-field">
          <label class="form-field__label" for="doc-category">{{ $t('documents.categoryLabel') }}</label>
          <select id="doc-category" v-model="formCategory" class="form-control">
            <option v-for="c in DOCUMENT_CATEGORIES" :key="c" :value="c">
              {{ $t(`documents.categories.${c}`) }}
            </option>
          </select>
        </div>

        <div class="form-row">
          <div class="form-field">
            <label class="form-field__label" for="doc-date">{{ $t('documents.documentDateLabel') }}</label>
            <input id="doc-date" v-model="formDocumentDate" type="date" class="form-control" />
          </div>
          <div class="form-field">
            <label class="form-field__label" for="doc-expiry">{{ $t('documents.expiryDateLabel') }}</label>
            <input id="doc-expiry" v-model="formExpiryDate" type="date" class="form-control" />
          </div>
        </div>
        <span class="form-field__hint">{{ $t('documents.expiryHint') }}</span>

        <div class="form-field">
          <label class="form-field__label" for="doc-notes">{{ $t('documents.notesLabel') }}</label>
          <textarea
            id="doc-notes"
            v-model="formNotes"
            class="form-control form-control--textarea"
            :placeholder="$t('documents.notesPlaceholder')"
            maxlength="2000"
            rows="3"
          />
        </div>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton v-if="editingDoc" variant="danger" :disabled="pagesBusy" @click="handleDelete">
            <PhTrash :size="16" />
            {{ $t('common.delete') }}
          </BaseButton>
          <span v-else />
          <BaseButton :disabled="!canSave || pagesBusy" :loading="formLoading" @click="handleSave">
            {{ editingDoc ? $t('common.save') : $t('documents.upload') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- Vorschau -->
    <BaseDialog
      :open="showPreview"
      :title="previewDoc?.title"
      @close="closePreview"
    >
      <div class="preview">
        <BaseSpinner v-if="previewLoading" />
        <template v-else-if="previewUrl && previewFile">
          <img
            v-if="previewFile.mime_type.startsWith('image/')"
            :src="previewUrl"
            :alt="previewFile.original_name"
            class="preview__image"
          />
          <iframe
            v-else
            :src="previewUrl"
            :title="previewFile.original_name"
            class="preview__pdf"
          />
        </template>
      </div>
      <template #footer>
        <div class="preview-footer">
          <div v-if="previewDoc && previewDoc.files.length > 1" class="preview-nav">
            <button class="icon-btn tap-target" :disabled="previewIndex === 0" :aria-label="$t('documents.previousPage')" @click="showPreviewPage(previewIndex - 1)">
              <PhCaretLeft :size="18" />
            </button>
            <span class="preview-nav__label">
              {{ $t('documents.pageOf', { current: previewIndex + 1, total: previewDoc.files.length }) }}
            </span>
            <button class="icon-btn tap-target" :disabled="previewIndex >= previewDoc.files.length - 1" :aria-label="$t('documents.nextPage')" @click="showPreviewPage(previewIndex + 1)">
              <PhCaretRight :size="18" />
            </button>
          </div>
          <span v-else />
          <BaseButton v-if="previewFile" variant="secondary" @click="handleDownload(previewFile)">
            <PhDownloadSimple :size="16" />
            {{ $t('documents.download') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.search {
  position: relative;
  margin: var(--space-3) 0;
}

.search__icon {
  position: absolute;
  left: var(--space-3);
  top: 50%;
  transform: translateY(-50%);
  color: var(--sub);
  pointer-events: none;
  z-index: 1;
}

.search :deep(.base-input__field) {
  padding-left: calc(var(--space-3) + 24px);
}

.category-tabs {
  margin-bottom: var(--space-4);
}

.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.doc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.doc-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  background: var(--card);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.doc-card:hover,
.doc-card:focus-visible {
  background: var(--chip);
  outline: none;
}

.doc-card__icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  background: var(--acc-soft);
  color: var(--acc);
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-card__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.doc-card__title {
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-base);
  color: var(--ink);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
}

.doc-card__date {
  font-size: var(--text-xs);
  color: var(--sub);
}

.doc-card__actions {
  display: flex;
  flex-shrink: 0;
  /* Abstand, damit sich die 44-px-Tap-Flächen (.tap-target) nicht überlappen */
  gap: var(--space-3);
}

.category-chip {
  background: var(--chip);
  border-radius: var(--radius-full);
  padding: 2px 10px;
  font-size: var(--text-xs);
  color: var(--sub);
}

.expiry-badge {
  border-radius: var(--radius-full);
  padding: 2px 10px;
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--card);
}

.expiry-badge--soon {
  background: var(--color-warning);
}

.expiry-badge--expired {
  background: var(--color-danger);
}

.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--sub);
  display: flex;
  align-items: center;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.icon-btn:hover {
  color: var(--acc);
  background: var(--acc-soft);
}

.load-more {
  display: flex;
  justify-content: center;
  margin-top: var(--space-4);
}

/* ── Formular ── */

.doc-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
  flex: 1;
}

.form-field :deep(.base-btn) {
  align-self: flex-start;
}

.form-field__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.form-field__hint {
  font-size: var(--text-xs);
  color: var(--sub);
  word-break: break-word;
  margin-top: calc(-1 * var(--space-2));
}

.form-field .form-field__hint {
  margin-top: 0;
}

.form-row {
  display: flex;
  gap: var(--space-3);
}

.file-input {
  display: none;
}

.form-control {
  width: 100%;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  font-family: inherit;
  font-size: var(--text-base);
  color: var(--ink);
  background: var(--card);
  min-height: 40px;
}

.form-control:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 2px var(--acc-soft);
}

.form-control--textarea {
  resize: vertical;
  line-height: var(--line-height-normal);
}

.dialog-actions {
  display: flex;
  justify-content: space-between;
  width: 100%;
  gap: var(--space-2);
}

/* ── Vorschau ── */

.preview {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}

.preview__image {
  max-width: 100%;
  max-height: 70vh;
  border-radius: var(--radius-sm);
}

.preview__pdf {
  width: 100%;
  height: 65vh;
  border: none;
  border-radius: var(--radius-sm);
}

/* ── Seiten ── */

.form-field__count {
  font-weight: var(--font-weight-normal);
  color: var(--sub);
}

.page-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.page-row {
  display: flex;
  align-items: center;
  /* Abstand, damit sich die 44-px-Tap-Flächen (.tap-target) nicht überlappen */
  gap: var(--space-3);
  background: var(--chip);
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-1) var(--space-1) var(--space-2);
}

.page-row__num {
  flex-shrink: 0;
  width: 20px;
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
}

.page-row__name {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  font-size: var(--text-sm);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.page-row__name small {
  font-size: var(--text-xs);
  color: var(--sub);
}

.page-row__name--link {
  background: none;
  border: none;
  padding: 0;
  font-family: inherit;
  cursor: pointer;
}

.page-row__name--link:disabled {
  cursor: default;
}

.page-row .icon-btn {
  padding: var(--space-2);
}

.icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  background: none;
  color: var(--sub);
}

.page-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.preview-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: var(--space-2);
}

.preview-nav {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.preview-nav__label {
  font-size: var(--text-sm);
  color: var(--sub);
  white-space: nowrap;
}

@media (max-width: 380px) {
  .form-row {
    flex-direction: column;
  }
}
</style>
