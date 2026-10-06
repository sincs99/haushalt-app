<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useNotesStore } from '../stores/notes'
import { useSocket } from '../composables/useSocket'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { waitForOverlayBack } from '../composables/useBackClose'
import { formatDateShort } from '../utils/dates'
import type { NoteItem } from '../types'

import PageHeader from '../components/ui/PageHeader.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import { PhPushPin, PhNote, PhTrash, PhPlus } from '@phosphor-icons/vue'

const { t } = useI18n()
const { run, isPending } = useAsyncAction()
const socket = useSocket()

const store = useNotesStore()
const { loadError, reloading, reload } = useLoader(() => store.fetchNotes())

const QUICK_ADD_ID = 'notes-quick-add'

// ── Quick-Add State ──
const quickAddTitle = ref('')

// ── Edit Dialog State ──
const showEditDialog = ref(false)
const editingNote = ref<NoteItem | null>(null)
const editTitle = ref('')
const editBody = ref('')
const editTag = ref('')
const editPinned = ref(false)
const editLoading = ref(false)
const showDiscardConfirm = ref(false)

// ── Member Name Lookup ──
function memberName(userId: string): string {
  const member = store.members.find((m) => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

// ── Body Preview ──
function bodyPreview(body: string): string {
  if (!body) return ''
  const firstLine = body.split('\n')[0]
  return firstLine.length > 80 ? firstLine.substring(0, 80) + '…' : firstLine
}

// ── Quick Add ──
async function handleQuickAdd() {
  const title = quickAddTitle.value.trim()
  if (!title) return

  // Feld sofort leeren (Notiz erscheint optimistisch); offline wird gar nicht
  // gesendet und der Text bleibt stehen, bei Fehler kommt er zurück.
  const ok = await run(async () => {
    quickAddTitle.value = ''
    await store.addNote(title)
  }, { key: `add:${title}`, error: t('notes.addError') })
  if (!ok && !quickAddTitle.value.trim()) quickAddTitle.value = title
}

function focusQuickAdd() {
  document.getElementById(QUICK_ADD_ID)?.focus()
}

// ── Edit Dialog ──
function openEditDialog(note: NoteItem) {
  editingNote.value = note
  editTitle.value = note.title
  editBody.value = note.body
  editTag.value = note.tag ?? ''
  editPinned.value = note.pinned
  showDiscardConfirm.value = false
  showEditDialog.value = true
}

function closeEditDialog() {
  showDiscardConfirm.value = false
  showEditDialog.value = false
  editingNote.value = null
}

/** Ungespeicherte Änderungen im Bearbeiten-Dialog? */
const editDirty = computed(() => {
  const note = editingNote.value
  if (!note) return false
  return editTitle.value !== note.title
    || editBody.value !== note.body
    || editTag.value !== (note.tag ?? '')
    || editPinned.value !== note.pinned
})

/** Overlay, Escape, Zurück, X und „Abbrechen“: bei Änderungen erst nachfragen. */
function requestCloseEdit() {
  if (showDiscardConfirm.value) return
  if (editDirty.value && !editLoading.value) {
    showDiscardConfirm.value = true
    return
  }
  closeEditDialog()
}

/** „Verwerfen“ in der Rückfrage: erst die Rückfrage, dann den Dialog schliessen (sauberer Verlauf für Zurück). */
async function discardEdit() {
  showDiscardConfirm.value = false
  await nextTick()
  await waitForOverlayBack()
  closeEditDialog()
}

async function handleSave() {
  if (!editingNote.value || !editTitle.value.trim() || editLoading.value) return

  editLoading.value = true
  try {
    const ok = await run(() => store.updateNote(editingNote.value!.id, {
      title: editTitle.value.trim(),
      body: editBody.value,
      tag: editTag.value.trim() || null,
      pinned: editPinned.value,
    }), { key: 'save', error: t('notes.saveError') })
    if (ok) closeEditDialog()
  } finally {
    editLoading.value = false
  }
}

/** Sofort löschen (Store ist optimistisch), mit „Rückgängig“ statt Rückfrage. */
async function handleDelete() {
  const note = editingNote.value
  if (!note) return
  const snapshot = { ...note }
  closeEditDialog()
  await run(() => store.deleteNote(snapshot.id), {
    key: `delete:${snapshot.id}`,
    success: t('notes.deleted'),
    undo: () => store.restoreNote(snapshot),
    error: t('notes.deleteError'),
  })
}

async function handleTogglePin(noteId: string) {
  await run(() => store.togglePin(noteId), { key: `pin:${noteId}`, error: t('notes.saveError') })
}

// ── Computed ──
const hasNotes = computed(() => store.items.length > 0)

// ── Socket Events ──
function handleReconnect() {
  reload()
}

function loadMembers() {
  // Mitglieder nur für Avatare/Namen – ein Fehler hier soll nicht zusätzlich melden
  store.fetchMembers().catch(() => {})
}

// ── Lifecycle ──
onMounted(() => {
  reload()
  loadMembers()

  socket.on('note_created', store.handleNoteCreated)
  socket.on('note_updated', store.handleNoteUpdated)
  socket.on('note_deleted', store.handleNoteDeleted)
  socket.onReconnect(handleReconnect)
})

onUnmounted(() => {
  socket.off('note_created', store.handleNoteCreated)
  socket.off('note_updated', store.handleNoteUpdated)
  socket.off('note_deleted', store.handleNoteDeleted)
  socket.offReconnect(handleReconnect)
})
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('notes.title')" />

    <!-- Quick-Add -->
    <form class="quick-add" @submit.prevent="handleQuickAdd">
      <BaseInput
        :id="QUICK_ADD_ID"
        v-model="quickAddTitle"
        :placeholder="$t('notes.addPlaceholder')"
        :aria-label="$t('notes.addLabel')"
        autocomplete="off"
        enterkeyhint="done"
      />
      <button
        type="submit"
        class="quick-add__btn"
        :disabled="!quickAddTitle.trim()"
        :aria-label="$t('common.add')"
      >
        <PhPlus :size="20" weight="bold" />
      </button>
    </form>

    <!-- Loading -->
    <template v-if="(store.loading || reloading) && store.items.length === 0 && !loadError">
      <div class="skeleton-list">
        <BaseSkeleton v-for="i in 3" :key="i" width="100%" height="80px" />
      </div>
    </template>

    <!-- Ladefehler -->
    <BaseErrorState
      v-else-if="loadError && !hasNotes"
      :retrying="reloading"
      @retry="reload"
    />

    <!-- Empty State -->
    <BaseEmptyState
      v-else-if="!hasNotes && !store.loading"
      :icon="PhNote"
      :title="$t('notes.emptyTitle')"
      :subtitle="$t('notes.emptySubtitle')"
    >
      <template #action>
        <BaseButton variant="secondary" size="sm" @click="focusQuickAdd">
          <PhPlus :size="16" />
          {{ $t('notes.emptyAction') }}
        </BaseButton>
      </template>
    </BaseEmptyState>

    <!-- Notes Content -->
    <template v-else>
      <!-- Pinned Section -->
      <section v-if="store.pinnedNotes.length > 0" class="notes-section">
        <h3 class="notes-section__header">{{ $t('notes.pinnedSection') }}</h3>
        <div class="notes-grid">
          <div
            v-for="note in store.pinnedNotes"
            :key="note.id"
            class="note-card note-card--pinned"
            role="button"
            tabindex="0"
            @click="openEditDialog(note)"
            @keydown.enter.self.prevent="openEditDialog(note)"
            @keydown.space.self.prevent="openEditDialog(note)"
          >
            <div class="note-card__top">
              <span class="note-card__title">{{ note.title }}</span>
              <button
                type="button"
                class="pin-btn pin-btn--active"
                @click.stop="handleTogglePin(note.id)"
                :aria-label="$t('notes.unpin')"
                :title="$t('notes.unpin')"
                aria-pressed="true"
              >
                <PhPushPin :size="16" weight="fill" />
              </button>
            </div>
            <p v-if="note.body" class="note-card__preview">{{ bodyPreview(note.body) }}</p>
            <span v-if="note.tag" class="tag-chip">{{ note.tag }}</span>
          </div>
        </div>
      </section>

      <!-- All Notes (unpinned) -->
      <section v-if="store.unpinnedNotes.length > 0" class="notes-section">
        <h3 class="notes-section__header">{{ $t('notes.allSection') }}</h3>
        <div class="notes-grid">
          <div
            v-for="note in store.unpinnedNotes"
            :key="note.id"
            class="note-card"
            role="button"
            tabindex="0"
            @click="openEditDialog(note)"
            @keydown.enter.self.prevent="openEditDialog(note)"
            @keydown.space.self.prevent="openEditDialog(note)"
          >
            <div class="note-card__top">
              <span class="note-card__title">{{ note.title }}</span>
              <button
                type="button"
                class="pin-btn"
                @click.stop="handleTogglePin(note.id)"
                :aria-label="$t('notes.pin')"
                :title="$t('notes.pin')"
                aria-pressed="false"
              >
                <PhPushPin :size="16" weight="regular" />
              </button>
            </div>
            <p v-if="note.body" class="note-card__preview">{{ bodyPreview(note.body) }}</p>
            <div class="note-card__meta">
              <BaseAvatar
                v-if="note.created_by_user_id"
                :name="memberName(note.created_by_user_id)"
                :user-id="note.created_by_user_id"
                size="sm"
              />
              <span class="note-card__date">{{ formatDateShort(note.created_at) }}</span>
            </div>
            <span v-if="note.tag" class="tag-chip">{{ note.tag }}</span>
          </div>
        </div>
      </section>
    </template>

    <!-- Edit Dialog -->
    <BaseDialog
      :open="showEditDialog"
      :title="$t('notes.editTitle')"
      @close="requestCloseEdit"
    >
      <form id="note-edit-form" class="edit-form" @submit.prevent="handleSave">
        <BaseInput
          v-model="editTitle"
          :label="$t('notes.titleLabel')"
          :placeholder="$t('notes.titlePlaceholder')"
          autocomplete="off"
        />

        <div class="form-field">
          <label class="form-field__label" for="note-edit-body">{{ $t('notes.bodyLabel') }}</label>
          <textarea
            id="note-edit-body"
            v-model="editBody"
            class="edit-textarea"
            :placeholder="$t('notes.bodyPlaceholder')"
            maxlength="5000"
            rows="5"
          />
        </div>

        <BaseInput
          v-model="editTag"
          :label="$t('notes.tagLabel')"
          :placeholder="$t('notes.tagPlaceholder')"
          autocomplete="off"
        />

        <label class="pin-toggle">
          <input type="checkbox" v-model="editPinned" />
          <PhPushPin :size="16" :weight="editPinned ? 'fill' : 'regular'" />
          {{ $t('notes.pinLabel') }}
        </label>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton
            variant="danger"
            :disabled="editLoading"
            :loading="!!editingNote && isPending(`delete:${editingNote.id}`)"
            @click="handleDelete"
          >
            <PhTrash :size="16" />
            {{ $t('common.delete') }}
          </BaseButton>
          <div class="dialog-actions__spacer" />
          <BaseButton variant="secondary" @click="requestCloseEdit">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton
            type="submit"
            form="note-edit-form"
            :disabled="!editTitle.trim()"
            :loading="editLoading"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- Rückfrage: ungespeicherte Änderungen verwerfen? -->
    <BaseDialog
      :open="showDiscardConfirm"
      :title="$t('notes.discardTitle')"
      danger
      @close="showDiscardConfirm = false"
    >
      <p class="discard-text">{{ $t('notes.discardText') }}</p>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="secondary" autofocus @click="showDiscardConfirm = false">
            {{ $t('notes.keepEditing') }}
          </BaseButton>
          <BaseButton variant="danger" @click="discardEdit">
            {{ $t('notes.discardConfirm') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.quick-add {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  margin-bottom: var(--space-4);
}

/* BaseInput soll den verfügbaren Platz einnehmen */
.quick-add :deep(.base-input) {
  flex: 1;
}

.quick-add__btn {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  border: none;
  background: var(--acc);
  color: var(--card);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: opacity var(--transition-fast), transform var(--transition-fast);
  margin-top: 0; /* Alignment mit Input */
}

.quick-add__btn:active {
  transform: scale(0.92);
}

.quick-add__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.notes-section {
  margin-bottom: var(--space-4);
}

.notes-section__header {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-sm);
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 var(--space-2);
}

.notes-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.note-card:focus-visible {
  outline: 2px solid var(--acc);
  outline-offset: 2px;
}

.note-card {
  background: var(--card);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: background var(--transition-fast);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.note-card:hover {
  background: var(--chip);
}

.note-card--pinned {
  background: var(--acc-soft);
}

.note-card--pinned:hover {
  background: var(--acc-soft);
  filter: brightness(0.97);
}

.note-card__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}

.note-card__title {
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-base);
  color: var(--ink);
  line-height: 1.3;
  min-width: 0;
  word-break: break-word;
}

.note-card__preview {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
  line-height: var(--line-height-normal);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-card__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.note-card__date {
  font-size: var(--text-xs);
  color: var(--sub);
}

.tag-chip {
  display: inline-block;
  background: var(--chip);
  border-radius: var(--radius-full);
  padding: 2px 10px;
  font-size: var(--text-xs);
  color: var(--sub);
  align-self: flex-start;
  margin-top: var(--space-1);
}

.pin-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  color: var(--sub);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  transition: color var(--transition-fast);
}

.pin-btn:hover {
  color: var(--acc);
}

.pin-btn--active {
  color: var(--acc);
}

/* ── Edit Dialog ── */

.edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-field__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.edit-textarea {
  width: 100%;
  min-height: 120px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  font-family: inherit;
  font-size: var(--text-base);
  color: var(--ink);
  background: var(--card);
  line-height: var(--line-height-normal);
}

.edit-textarea:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 2px var(--acc-soft);
}

.edit-textarea::placeholder {
  color: var(--sub);
}

.pin-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--ink);
  cursor: pointer;
  user-select: none;
}

.pin-toggle input[type='checkbox'] {
  width: 16px;
  height: 16px;
  accent-color: var(--acc);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  width: 100%;
  gap: var(--space-2);
}

.dialog-actions__spacer {
  flex: 1;
}

.discard-text {
  margin: 0;
  color: var(--ink);
  font-size: var(--text-sm);
}
</style>
