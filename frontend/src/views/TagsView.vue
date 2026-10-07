<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useTagsStore } from '../stores/tags'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { useNfcWriter } from '../composables/useNfcWriter'
import { formatDateShort } from '../utils/dates'
import { qrSvgDataUrl } from '../utils/qr'
import { tagUrl } from '../utils/tagScan'
import type { TagInfo } from '../types'

import PageHeader from '../components/ui/PageHeader.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import { PhPlus, PhQrCode, PhCopy, PhDownloadSimple, PhArrowsClockwise, PhTrash, PhContactlessPayment, PhWarningCircle } from '@phosphor-icons/vue'

const { t, te } = useI18n()
const { notifySuccess, notifyError } = useToast()
const { run, isPending, anyPending } = useAsyncAction()
const socket = useSocket()
const authStore = useAuthStore()
const store = useTagsStore()
const nfc = useNfcWriter()

const isAdmin = computed(() => authStore.currentHousehold?.role === 'admin')

// ── Labels (Fallback auf den Schlüssel für Aktionen, die das Frontend noch nicht kennt) ──
function targetTypeLabel(type: string): string {
  const key = `tags.targetTypes.${type}`
  return te(key) ? t(key) : type
}

function actionLabel(action: string): string {
  const key = `tags.actions.${action}.label`
  return te(key) ? t(key) : action
}

function noTargetLabel(type: string): string {
  const key = `tags.targetNone.${type}`
  return te(key) ? t(key) : t('tags.targetNoneDefault')
}

function targetText(tag: TagInfo): string {
  if (tag.target_missing) return t('tags.targetMissing')
  return tag.target_name ?? noTargetLabel(tag.target_type)
}

function usageText(tag: TagInfo): string {
  if (!tag.last_used_at) return t('tags.neverUsed')
  return `${t('tags.useCount', { count: tag.use_count })}, ${t('tags.lastUsed', { date: formatDateShort(tag.last_used_at) })}`
}

// ── Anlegen ──
const showCreate = ref(false)
const createLabel = ref('')
const createType = ref('')
const createTarget = ref('')  // '' = keins / bitte wählen
const createAction = ref('')
const creating = ref(false)

const selectedType = computed(() => store.targets.find((tt) => tt.target_type === createType.value))
const selectedAction = computed(() => selectedType.value?.actions.find((a) => a.key === createAction.value))
const targetOptional = computed(() => selectedAction.value?.target_optional ?? false)
const canCreate = computed(
  () =>
    !!createLabel.value.trim() &&
    !!selectedAction.value &&
    (targetOptional.value || !!createTarget.value),
)

watch(createType, () => {
  createAction.value = selectedType.value?.actions[0]?.key ?? ''
  createTarget.value = ''
})

async function openCreate() {
  createLabel.value = ''
  createType.value = ''
  createTarget.value = ''
  createAction.value = ''
  showCreate.value = true
  try {
    await store.fetchTargets()
    createType.value = store.targets[0]?.target_type ?? ''
  } catch (err) {
    notifyError(t('tags.loadTargetsError'), err)
  }
}

async function handleCreate() {
  if (!canCreate.value || creating.value) return
  creating.value = true
  let tag = undefined as TagInfo | undefined
  const ok = await run(async () => {
    tag = await store.createTag({
      label: createLabel.value.trim(),
      target_type: createType.value,
      target_id: createTarget.value || null,
      action: createAction.value,
    })
  }, { key: 'create', error: t('tags.createError') })
  creating.value = false
  if (!ok) return
  // Ergebnis ist direkt sichtbar (Detail-Dialog öffnet sich) → kein Toast nötig
  showCreate.value = false
  if (tag) openDetail(tag)
}

// ── Detail (QR, URL, NFC, Verwaltung) ──
const detailId = ref<string | null>(null)
const detail = computed(() => store.items.find((tag) => tag.id === detailId.value) ?? null)
const editLabel = ref('')
const busy = computed(() => anyPending())
/** Bestätigung im Detail-Dialog (statt confirm(); ein zweiter Dialog darüber würde mit Escape beide schliessen) */
const pendingConfirm = ref<'regenerate' | 'delete' | null>(null)

const detailUrl = computed(() => (detail.value ? tagUrl(detail.value.token, window.location.origin) : ''))
const detailQr = computed(() => (detailUrl.value ? qrSvgDataUrl(detailUrl.value) : ''))
const qrFileName = computed(() => `tag-${(detail.value?.label ?? 'qr').replace(/[^\p{L}\p{N}_-]+/gu, '-')}.svg`)

function openDetail(tag: TagInfo) {
  detailId.value = tag.id
  editLabel.value = tag.label
  pendingConfirm.value = null
}

function closeDetail() {
  if (nfc.writing.value) nfc.cancel()
  detailId.value = null
  pendingConfirm.value = null
}

// Tag wurde von jemand anderem gelöscht → Dialog schliessen
watch(detail, (value) => {
  if (detailId.value && !value) detailId.value = null
})

async function copyUrl() {
  try {
    await navigator.clipboard.writeText(detailUrl.value)
    notifySuccess(t('tags.urlCopied'))
  } catch {
    notifyError(t('tags.copyFailed'))
  }
}

async function writeNfc() {
  try {
    await nfc.writeUrl(detailUrl.value)
    notifySuccess(t('tags.nfcSuccess'))
  } catch (err: any) {
    if (err?.kind === 'aborted') return
    notifyError(err?.kind === 'permission' ? t('tags.nfcPermission') : t('tags.nfcError'))
  }
}

async function saveLabel() {
  const tag = detail.value
  const label = editLabel.value.trim()
  if (!tag || !label || label === tag.label) return
  await run(() => store.updateTag(tag.id, { label }), {
    key: 'label',
    success: t('tags.labelSaved'),
    error: t('tags.saveError'),
  })
}

async function toggleEnabled() {
  const tag = detail.value
  if (!tag) return
  // Ergebnis sichtbar (Badge + Button-Text) → kein Toast
  await run(() => store.setEnabled(tag.id, !tag.enabled), { key: 'enabled', error: t('tags.saveError') })
}

async function regenerate() {
  const tag = detail.value
  if (!tag) return
  const ok = await run(() => store.regenerateToken(tag.id), {
    key: 'regenerate',
    success: t('tags.regenerateSuccess'),
    error: t('tags.saveError'),
  })
  if (ok) pendingConfirm.value = null
}

async function remove() {
  const tag = detail.value
  if (!tag) return
  const ok = await run(() => store.deleteTag(tag.id), {
    key: 'delete',
    success: t('tags.deleted'),
    error: t('tags.deleteError'),
  })
  if (ok) closeDetail()
}

// ── Socket + Lifecycle ──
// Laden mit Fehlerzustand (statt „Noch keine Tags“ nach einem Ladefehler)
const { loadError, reloading, reload: load } = useLoader(() => store.fetchTags())

onMounted(() => {
  load()
  socket.on('tag_created', store.handleTagCreated)
  socket.on('tag_updated', store.handleTagUpdated)
  socket.on('tag_deleted', store.handleTagDeleted)
  socket.onReconnect(load)
})

onUnmounted(() => {
  socket.off('tag_created', store.handleTagCreated)
  socket.off('tag_updated', store.handleTagUpdated)
  socket.off('tag_deleted', store.handleTagDeleted)
  socket.offReconnect(load)
  if (nfc.writing.value) nfc.cancel()
})

watch(() => authStore.currentHouseholdId, () => {
  detailId.value = null
  store.$reset()
  load()
})
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('tags.title')" :subtitle="$t('tags.subtitle')">
      <template #actions>
        <BaseButton v-if="isAdmin" size="sm" @click="openCreate">
          <PhPlus :size="16" weight="bold" />
          {{ $t('tags.add') }}
        </BaseButton>
      </template>
    </PageHeader>

    <p v-if="!isAdmin" class="hint">{{ $t('tags.adminOnly') }}</p>

    <div v-if="store.loading && store.items.length === 0" class="tag-list">
      <BaseSkeleton v-for="i in 3" :key="i" width="100%" height="64px" />
    </div>

    <BaseErrorState
      v-else-if="loadError && store.items.length === 0"
      :retrying="reloading"
      @retry="load"
    />

    <BaseEmptyState
      v-else-if="store.items.length === 0"
      :icon="PhQrCode"
      :title="$t('tags.emptyTitle')"
      :subtitle="$t('tags.emptySubtitle')"
    >
      <template v-if="isAdmin" #action>
        <BaseButton size="sm" @click="openCreate">
          <PhPlus :size="16" weight="bold" />
          {{ $t('tags.add') }}
        </BaseButton>
      </template>
    </BaseEmptyState>

    <ul v-else class="tag-list">
      <li v-for="tag in store.sortedTags" :key="tag.id">
        <button
          type="button"
          class="tag-row"
          :class="{ 'tag-row--disabled': !tag.enabled }"
          @click="openDetail(tag)"
        >
          <PhQrCode :size="24" class="tag-row__icon" />
          <span class="tag-row__body">
            <span class="tag-row__title">
              {{ tag.label }}
              <span v-if="!tag.enabled" class="badge">{{ $t('tags.disabledBadge') }}</span>
            </span>
            <span class="tag-row__meta" :class="{ 'tag-row__meta--warn': tag.target_missing }">
              {{ actionLabel(tag.action) }} · {{ targetText(tag) }}
            </span>
            <span class="tag-row__meta">{{ usageText(tag) }}</span>
          </span>
        </button>
      </li>
    </ul>

    <!-- Anlegen -->
    <BaseDialog :open="showCreate" :title="$t('tags.add')" @close="showCreate = false">
      <form id="tag-create-form" class="form" @submit.prevent="handleCreate">
        <BaseInput
          v-model="createLabel"
          :label="$t('tags.labelLabel')"
          :placeholder="$t('tags.labelPlaceholder')"
          maxlength="80"
          autocomplete="off"
        />

        <label class="field">
          <span class="field__label">{{ $t('tags.targetTypeLabel') }}</span>
          <select v-model="createType" class="field__select">
            <option v-for="tt in store.targets" :key="tt.target_type" :value="tt.target_type">
              {{ targetTypeLabel(tt.target_type) }}
            </option>
          </select>
        </label>

        <label v-if="selectedType" class="field">
          <span class="field__label">{{ $t('tags.targetLabel') }}</span>
          <select v-model="createTarget" class="field__select">
            <option value="" :disabled="!targetOptional">
              {{ targetOptional ? noTargetLabel(createType) : $t('tags.targetChoose') }}
            </option>
            <option v-for="opt in selectedType.options" :key="opt.id" :value="opt.id">
              {{ opt.name }}
            </option>
          </select>
          <span v-if="selectedType.options.length === 0 && !targetOptional" class="field__hint">
            {{ $t('tags.noTargets') }}
          </span>
        </label>

        <label v-if="selectedType && selectedType.actions.length > 1" class="field">
          <span class="field__label">{{ $t('tags.actionLabel') }}</span>
          <select v-model="createAction" class="field__select">
            <option v-for="a in selectedType.actions" :key="a.key" :value="a.key">
              {{ actionLabel(a.key) }}
            </option>
          </select>
        </label>
        <p v-else-if="selectedAction" class="field__hint">
          {{ $t('tags.actionLabel') }}: {{ actionLabel(selectedAction.key) }}
        </p>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="showCreate = false">{{ $t('common.cancel') }}</BaseButton>
          <BaseButton type="submit" form="tag-create-form" :disabled="!canCreate" :loading="creating">
            {{ $t('tags.add') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- Detail -->
    <BaseDialog :open="!!detail" :title="detail?.label" @close="closeDetail">
      <div v-if="detail" class="detail">
        <p class="detail__meta">
          {{ actionLabel(detail.action) }} · {{ targetText(detail) }}
          <span v-if="!detail.enabled" class="badge">{{ $t('tags.disabledBadge') }}</span>
        </p>

        <section class="detail__section">
          <h3 class="detail__heading">{{ $t('tags.qrTitle') }}</h3>
          <img class="qr" :src="detailQr" :alt="$t('tags.qrAlt', { label: detail.label })" width="220" height="220" />
          <p class="field__hint">{{ $t('tags.qrHint') }}</p>
          <a class="link-btn tap-target" :href="detailQr" :download="qrFileName">
            <PhDownloadSimple :size="16" /> {{ $t('tags.downloadQr') }}
          </a>
        </section>

        <section class="detail__section">
          <h3 class="detail__heading">{{ $t('tags.url') }}</h3>
          <code class="url">{{ detailUrl }}</code>
          <BaseButton variant="secondary" size="sm" @click="copyUrl">
            <PhCopy :size="16" /> {{ $t('tags.copyUrl') }}
          </BaseButton>
        </section>

        <section class="detail__section">
          <h3 class="detail__heading">{{ $t('tags.nfcTitle') }}</h3>
          <template v-if="nfc.supported">
            <BaseButton v-if="!nfc.writing.value" variant="secondary" size="sm" @click="writeNfc">
              <PhContactlessPayment :size="16" /> {{ $t('tags.nfcWrite') }}
            </BaseButton>
            <div v-else class="nfc-wait">
              <span>{{ $t('tags.nfcHold') }}</span>
              <BaseButton variant="ghost" size="sm" @click="nfc.cancel()">{{ $t('tags.nfcCancel') }}</BaseButton>
            </div>
          </template>
          <p v-else class="field__hint">{{ $t('tags.nfcUnsupported') }}</p>
        </section>

        <section v-if="isAdmin" class="detail__section">
          <form class="rename-row" @submit.prevent="saveLabel">
            <BaseInput v-model="editLabel" :label="$t('tags.labelLabel')" maxlength="80" />
            <BaseButton
              type="submit"
              size="sm"
              :loading="isPending('label')"
              :disabled="busy || !editLabel.trim() || editLabel.trim() === detail.label"
            >
              {{ $t('common.save') }}
            </BaseButton>
          </form>

          <!-- Bestätigung: Token neu erzeugen / Tag löschen -->
          <div v-if="pendingConfirm" class="confirm-box" role="alertdialog" aria-live="assertive">
            <p class="confirm-box__text">
              <PhWarningCircle :size="18" aria-hidden="true" />
              {{ pendingConfirm === 'delete' ? $t('tags.deleteConfirm', { label: detail.label }) : $t('tags.regenerateConfirm') }}
            </p>
            <div class="admin-actions">
              <BaseButton variant="ghost" size="sm" :disabled="busy" @click="pendingConfirm = null">
                {{ $t('common.cancel') }}
              </BaseButton>
              <BaseButton
                v-if="pendingConfirm === 'delete'"
                variant="danger"
                size="sm"
                :loading="isPending('delete')"
                @click="remove"
              >
                <PhTrash :size="16" /> {{ $t('tags.deleteTitle') }}
              </BaseButton>
              <BaseButton
                v-else
                variant="danger"
                size="sm"
                :loading="isPending('regenerate')"
                @click="regenerate"
              >
                <PhArrowsClockwise :size="16" /> {{ $t('tags.regenerate') }}
              </BaseButton>
            </div>
          </div>
          <div v-else class="admin-actions">
            <BaseButton variant="secondary" size="sm" :loading="isPending('enabled')" :disabled="busy" @click="toggleEnabled">
              {{ detail.enabled ? $t('tags.disable') : $t('tags.enable') }}
            </BaseButton>
            <BaseButton variant="ghost" size="sm" :disabled="busy" @click="pendingConfirm = 'regenerate'">
              <PhArrowsClockwise :size="16" /> {{ $t('tags.regenerate') }}
            </BaseButton>
            <BaseButton variant="danger" size="sm" :disabled="busy" @click="pendingConfirm = 'delete'">
              <PhTrash :size="16" /> {{ $t('common.delete') }}
            </BaseButton>
          </div>
        </section>
      </div>
    </BaseDialog>
  </div>
</template>

<style scoped>
.hint {
  color: var(--sub);
  font-size: var(--text-sm);
  margin: 0 0 var(--space-3);
}

.confirm-box {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.confirm-box__text {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
}

.tag-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.tag-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--card);
  border: none;
  border-radius: var(--radius-item);
  box-shadow: var(--shadow-card);
  text-align: left;
  color: var(--ink);
  font: inherit;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.tag-row:hover {
  background: var(--chip);
}

.tag-row--disabled {
  opacity: 0.6;
}

.tag-row__icon {
  flex-shrink: 0;
  color: var(--acc);
}

.tag-row__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
}

.tag-row__title {
  font-weight: var(--font-weight-semibold);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-title-item);
}

.tag-row__meta {
  font-size: var(--text-sm);
  color: var(--sub);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-row__meta--warn {
  color: var(--color-danger);
}

.badge {
  font-size: var(--text-badge);
  font-weight: var(--font-weight-semibold);
  padding: var(--badge-padding);
  border-radius: var(--radius-full);
  background: var(--chip);
  color: var(--sub);
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.field__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.field__select {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-size: var(--text-base); /* iOS-Zoom verhindern */
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
}

.field__select:focus {
  outline: none;
  border-color: var(--acc);
}

.field__hint {
  font-size: var(--text-sm);
  color: var(--sub);
  margin: 0;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.detail__meta {
  margin: 0;
  color: var(--sub);
  font-size: var(--text-sm);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.detail__section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.detail__heading {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.qr {
  align-self: center;
  width: 220px;
  height: 220px;
  background: #fff; /* bewusst: QR-Codes brauchen weissen Grund, auch im Dark Mode */
  border-radius: var(--radius-sm);
  image-rendering: pixelated;
}

.url {
  display: block;
  width: 100%;
  padding: var(--space-2);
  background: var(--chip);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  word-break: break-all;
}

.link-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--acc);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  text-decoration: none;
}

.nfc-wait {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: var(--text-sm);
}

.rename-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  width: 100%;
}

.rename-row :deep(.base-input) {
  flex: 1;
}

.admin-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
