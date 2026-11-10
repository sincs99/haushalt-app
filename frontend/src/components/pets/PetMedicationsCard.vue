<script setup lang="ts">
/**
 * Medikamente auf der Tier-Detailseite: aktive (mit Gabe und Verlauf) und inaktive Liste,
 * Rückfrage bei erneuter Gabe kurz nach der letzten (PD-P1), Löschen bzw. Deaktivieren
 * (PD-P2) und der Anlegen/Bearbeiten-Dialog. Die Gaben-Logs lädt die Detailseite.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePetsStore } from '../../stores/pets'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { localDateString } from '../../utils/dates'
import { formatClock, isRecentDose, lastDose, MEDICATION_CONFIRM_HOURS } from '../../utils/petCare'
import type { Medication } from '../../types'
import { PhPencilSimple, PhPlus, PhPill, PhCheck, PhTrash, PhUser } from '@phosphor-icons/vue'
import BaseCard from '../ui/BaseCard.vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseDialog from '../ui/BaseDialog.vue'
import PetMedicationFormDialog from './PetMedicationFormDialog.vue'

const props = defineProps<{
  petId: string
}>()

const petsStore = usePetsStore()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const activeMedications = computed(() =>
  petsStore.medications.filter(m => m.active),
)

const inactiveMedications = computed(() =>
  petsStore.medications.filter(m => !m.active),
)

function getMemberName(userId: string): string {
  const member = petsStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

// ── Medication Helpers ──

function isGivenToday(medicationId: string): boolean {
  const last = lastDose(petsStore.medicationLogs[medicationId])
  // Lokales Datum, nicht UTC (sonst gilt nachts die Gabe von gestern als heute)
  return !!last && localDateString(new Date(last.given_at)) === localDateString()
}

/** „Zuletzt gegeben um HH:MM von X“ (heute) bzw. mit Datum (früher) — PD-P1. */
function lastGivenText(medicationId: string): string {
  const last = lastDose(petsStore.medicationLogs[medicationId])
  if (!last) return t('pets.notGivenYet')
  const name = getMemberName(last.given_by_user_id)
  if (isGivenToday(medicationId)) return t('pets.lastGivenToday', { time: formatClock(last.given_at), name })
  return t('pets.lastGivenAt', { date: formatLogDateTime(last.given_at), name })
}

function formatLogDateTime(givenAt: string): string {
  const d = new Date(givenAt)
  return d.toLocaleDateString('de-CH', {
    day: '2-digit',
    month: '2-digit',
  }) + ' ' + d.toLocaleTimeString('de-CH', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Geben ist immer möglich (auch mehrmals täglich, PD-P1). Liegt die letzte Gabe weniger als
// MEDICATION_CONFIRM_HOURS zurück, erst nachfragen (zeigt wann und von wem).
// Guard gegen Doppeltipp (sonst zwei Gaben). Kein Undo: Backend kann Gaben nicht löschen.
const confirmGiveMedId = ref<string | null>(null)
const confirmGiveText = computed(() => {
  const last = confirmGiveMedId.value ? lastDose(petsStore.medicationLogs[confirmGiveMedId.value]) : null
  if (!last) return ''
  return t('pets.giveAgainHint', {
    time: formatClock(last.given_at),
    name: getMemberName(last.given_by_user_id),
    hours: MEDICATION_CONFIRM_HOURS,
  })
})

function requestGiveMedication(medicationId: string) {
  if (isRecentDose(lastDose(petsStore.medicationLogs[medicationId]))) {
    confirmGiveMedId.value = medicationId
    return
  }
  return handleGiveMedication(medicationId)
}

async function confirmGiveAgain() {
  const medId = confirmGiveMedId.value
  if (!medId) return
  confirmGiveMedId.value = null
  await handleGiveMedication(medId)
}

function handleGiveMedication(medicationId: string) {
  return run(() => petsStore.giveMedication(props.petId, medicationId), {
    key: `give-${medicationId}`,
    success: t('pets.medicationGiven'),
    error: t('pets.medicationGiveError'),
  })
}

// ── Add / Edit Medication Dialog ──

const showMedDialog = ref(false)
const editingMed = ref<Medication | null>(null)

function openAddMedDialog() {
  editingMed.value = null
  showMedDialog.value = true
}

function openEditMedDialog(med: Medication) {
  editingMed.value = med
  showMedDialog.value = true
}

// ── Delete Medication ──
// Medikamente mit Gaben-Verlauf lassen sich nicht löschen (409 MEDICATION_HAS_HISTORY,
// PD-P2) — der Dialog bietet dann „Deaktivieren“ an; der Verlauf bleibt erhalten.

const deletingMedId = ref<string | null>(null)
const deletingMedHasHistory = ref(false)
const deletingMed = computed(() => petsStore.medications.find(m => m.id === deletingMedId.value) ?? null)

function confirmDeleteMed(medId: string) {
  deletingMedId.value = medId
  deletingMedHasHistory.value = (petsStore.medicationLogs[medId] ?? []).length > 0
}

function cancelDeleteMed() {
  deletingMedId.value = null
}

function isHistoryConflict(err: unknown): boolean {
  const e = err as { response?: { data?: { detail?: { code?: string } } } }
  return e?.response?.data?.detail?.code === 'MEDICATION_HAS_HISTORY'
}

async function handleDeleteMed() {
  const medId = deletingMedId.value
  if (!medId) return
  let hasHistory = false
  const ok = await run(async () => {
    try {
      await petsStore.removeMedication(props.petId, medId)
      return true
    } catch (err) {
      // Andere Person hat inzwischen eine Gabe erfasst → Dialog auf „Deaktivieren“ umstellen
      if (!isHistoryConflict(err)) throw err
      hasHistory = true
      return false
    }
  }, {
    key: 'med-delete',
    success: (deleted) => (deleted ? t('pets.medicationDeleted') : undefined),
    error: t('pets.medicationDeleteError'),
  })
  if (hasHistory) deletingMedHasHistory.value = true
  else if (ok) deletingMedId.value = null
}

async function handleDeactivateMed() {
  const medId = deletingMedId.value
  if (!medId) return
  const ok = await run(() => petsStore.updateMedication(props.petId, medId, { active: false }), {
    key: 'med-delete',
    success: t('pets.medicationDeactivated'),
    error: t('pets.medicationSaveError'),
  })
  if (ok) deletingMedId.value = null
}
</script>

<template>
  <!-- ═══ Medikamente ═══ -->
  <section class="section">
    <BaseCard>
      <h2 class="card-title">{{ $t('pets.medications') }}</h2>

      <!-- Keine Medikamente -->
      <div v-if="petsStore.medications.length === 0" class="med-empty">
        <PhPill :size="32" weight="regular" class="med-empty__icon" />
        <p class="med-empty__title">{{ $t('pets.noMedications') }}</p>
        <p class="med-empty__hint">{{ $t('pets.noMedicationsHint') }}</p>
      </div>

      <!-- Aktive Medikamente -->
      <ul v-if="activeMedications.length > 0" class="med-list">
        <li
          v-for="med in activeMedications"
          :key="med.id"
          class="med-item"
        >
          <div class="med-item__header">
            <div
              class="med-check"
              :class="{ 'med-check--given': isGivenToday(med.id) }"
            >
              <PhCheck v-if="isGivenToday(med.id)" :size="12" weight="bold" />
            </div>
            <div class="med-item__info">
              <span class="med-item__name">{{ med.name }}</span>
              <span v-if="med.dosage || med.schedule" class="med-item__meta">
                <template v-if="med.dosage">{{ med.dosage }}</template>
                <template v-if="med.dosage && med.schedule"> · </template>
                <template v-if="med.schedule">{{ med.schedule }}</template>
              </span>
              <span class="med-item__status" :class="isGivenToday(med.id) ? 'med-item__status--given' : 'med-item__status--pending'">
                {{ lastGivenText(med.id) }}
              </span>
            </div>
            <div class="med-item__actions">
              <button
                class="med-action-btn med-action-btn--edit tap-target"
                @click="openEditMedDialog(med)"
                :aria-label="$t('common.edit')"
              >
                <PhPencilSimple :size="16" />
              </button>
              <button
                class="med-action-btn med-action-btn--delete tap-target"
                @click="confirmDeleteMed(med.id)"
                :aria-label="$t('common.delete')"
              >
                <PhTrash :size="16" />
              </button>
            </div>
          </div>

          <!-- Give Button: immer verfügbar (mehrere Gaben pro Tag, PD-P1) -->
          <BaseButton
            :variant="isGivenToday(med.id) ? 'secondary' : 'primary'"
            size="sm"
            class="med-give-btn"
            :loading="isPending(`give-${med.id}`)"
            @click="requestGiveMedication(med.id)"
          >
            {{ isGivenToday(med.id) ? $t('pets.giveAgain') : $t('pets.giveNow') }}
          </BaseButton>

          <!-- Letzte Gaben -->
          <div
            v-if="(petsStore.medicationLogs[med.id] ?? []).length > 0"
            class="med-log"
          >
            <span class="med-log__title">{{ $t('pets.lastGiven') }}</span>
            <ul class="med-log__list">
              <li
                v-for="log in petsStore.medicationLogs[med.id]"
                :key="log.id"
                class="med-log__entry"
              >
                <span class="med-log__user"><PhUser :size="12" aria-hidden="true" /> {{ getMemberName(log.given_by_user_id) }}</span>
                <span class="med-log__time">{{ formatLogDateTime(log.given_at) }}</span>
              </li>
            </ul>
          </div>
        </li>
      </ul>

      <!-- Inaktive Medikamente -->
      <div v-if="inactiveMedications.length > 0" class="med-inactive-section">
        <ul class="med-list">
          <li
            v-for="med in inactiveMedications"
            :key="med.id"
            class="med-item med-item--inactive"
          >
            <div class="med-item__header">
              <div class="med-check med-check--inactive">●</div>
              <div class="med-item__info">
                <span class="med-item__name">{{ med.name }}
                  <span class="med-item__badge">{{ $t('pets.medicationInactive') }}</span>
                </span>
                <span v-if="med.dosage || med.schedule" class="med-item__meta">
                  <template v-if="med.dosage">{{ med.dosage }}</template>
                  <template v-if="med.dosage && med.schedule"> · </template>
                  <template v-if="med.schedule">{{ med.schedule }}</template>
                </span>
              </div>
              <div class="med-item__actions">
                <button
                  class="med-action-btn med-action-btn--edit tap-target"
                  @click="openEditMedDialog(med)"
                  :aria-label="$t('common.edit')"
                >
                  <PhPencilSimple :size="16" />
                </button>
                <button
                  class="med-action-btn med-action-btn--delete tap-target"
                  @click="confirmDeleteMed(med.id)"
                  :aria-label="$t('common.delete')"
                >
                  <PhTrash :size="16" />
                </button>
              </div>
            </div>
          </li>
        </ul>
      </div>

      <!-- Add Medication Button -->
      <BaseButton
        variant="secondary"
        size="sm"
        class="med-add-btn"
        @click="openAddMedDialog"
      >
        <PhPlus :size="16" weight="bold" />
        {{ $t('pets.addMedication') }}
      </BaseButton>
    </BaseCard>
  </section>

  <PetMedicationFormDialog v-model="showMedDialog" :pet-id="petId" :medication="editingMed" />

  <!-- ═══ Delete Medication Confirm (mit Verlauf → Deaktivieren) ═══ -->
  <BaseDialog
    :open="!!deletingMedId"
    :title="deletingMedHasHistory ? $t('pets.medicationHasHistoryTitle') : $t('pets.deleteMedicationConfirm')"
    :danger="!deletingMedHasHistory"
    @close="cancelDeleteMed"
  >
    <p v-if="deletingMedHasHistory" class="dialog-hint">
      {{ $t('pets.medicationHasHistoryHint', { name: deletingMed?.name ?? '' }) }}
    </p>
    <template #footer>
      <div class="dialog-actions">
        <BaseButton variant="ghost" @click="cancelDeleteMed">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          v-if="deletingMedHasHistory"
          variant="primary"
          :disabled="!deletingMed?.active"
          :loading="isPending('med-delete')"
          @click="handleDeactivateMed"
        >
          {{ $t('pets.deactivateMedication') }}
        </BaseButton>
        <BaseButton v-else variant="danger" :loading="isPending('med-delete')" @click="handleDeleteMed">
          {{ $t('common.delete') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>

  <!-- ═══ Erneute Gabe kurz nach der letzten bestätigen (PD-P1) ═══ -->
  <BaseDialog
    :open="!!confirmGiveMedId"
    :title="$t('pets.giveAgainTitle')"
    @close="confirmGiveMedId = null"
  >
    <p class="dialog-hint">{{ confirmGiveText }}</p>
    <template #footer>
      <div class="dialog-actions">
        <BaseButton variant="ghost" @click="confirmGiveMedId = null">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton variant="primary" @click="confirmGiveAgain">
          {{ $t('pets.giveAgainConfirm') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>

<style scoped>
/* ── Section ── */
.section {
  margin-bottom: var(--space-4);
}

/* ── Card Title ── */
.card-title {
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-3) 0;
  color: var(--ink);
}

/* ── Medications ── */
.med-empty {
  text-align: center;
  padding: var(--space-4) 0;
}

.med-empty__icon {
  color: var(--sub);
  margin-bottom: var(--space-2);
}

.med-empty__title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0 0 var(--space-1) 0;
}

.med-empty__hint {
  font-size: var(--text-xs);
  color: var(--sub);
  margin: 0;
}

.med-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.med-item {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--line);
}

.med-item:last-child {
  border-bottom: none;
}

.med-item--inactive {
  opacity: 0.5;
}

.med-item__header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.med-check {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-full);
  border: 2px solid var(--line-strong);
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: var(--space-0-5);
  font-size: var(--text-2xs);
  color: var(--sub);
}

.med-check--given {
  background: var(--ok);
  border-color: var(--ok);
  color: var(--color-on-success);
}

.med-check--inactive {
  border-color: var(--sub);
  color: var(--sub);
  font-size: var(--text-2xs);
}

.med-item__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
}

.med-item__name {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.med-item__badge {
  font-size: var(--text-badge);
  font-weight: var(--font-weight-normal);
  color: var(--sub);
  background: var(--chip);
  padding: var(--badge-padding);
  border-radius: var(--radius-full);
  margin-left: var(--space-1);
}

.med-item__meta {
  font-size: var(--text-xs);
  color: var(--sub);
}

.med-item__status {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-medium);
}

.med-item__status--given {
  color: var(--ok);
}

.med-item__status--pending {
  color: var(--color-warning-strong);
}

.med-item__actions {
  display: flex;
  /* Abstand, damit sich die 44-px-Tap-Flächen (.tap-target) nicht überlappen */
  gap: var(--space-3);
  flex-shrink: 0;
}

.med-action-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  color: var(--sub);
}

.med-action-btn:hover {
  background: var(--chip);
}

.med-action-btn--delete:hover {
  color: var(--color-danger);
}

.med-give-btn {
  margin-top: var(--space-2);
  margin-left: 30px;
}

.med-log {
  margin-top: var(--space-2);
  margin-left: 30px;
  padding-top: var(--space-2);
  border-top: 1px dashed var(--line);
}

.med-log__title {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  display: block;
  margin-bottom: var(--space-1);
}

.med-log__list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.med-log__entry {
  font-size: var(--text-xs);
  color: var(--sub);
  display: flex;
  gap: var(--space-2);
}

.med-log__user {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: var(--font-weight-medium);
}

.med-log__time {
  color: var(--sub);
}

.med-inactive-section {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--line);
}

.med-add-btn {
  margin-top: var(--space-3);
  width: 100%;
}

/* ── Dialog ── */
.dialog-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--sub);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
