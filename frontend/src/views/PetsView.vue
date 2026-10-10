<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { usePetsStore } from '../stores/pets'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { parseWeightKgToGrams } from '../utils/money'
import { activePets, archivedPets, formatClock, hasHistory, needsUnfeedConfirmation, petHistoryConflict } from '../utils/petCare'
import type { Pet, PetCreatePayload, PetHistory, FeedingSlot, FeedingLog } from '../types'
import { PhCat, PhSun, PhMoon, PhPlus } from '@phosphor-icons/vue'
import PetPhotoAvatar from '../components/PetPhotoAvatar.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import PageHeader from '../components/ui/PageHeader.vue'

const petsStore = usePetsStore()
const authStore = useAuthStore()
const router = useRouter()
const { on, off, onReconnect, offReconnect } = useSocket()
const { notifyInfo } = useToast()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

// Ladefehler → Fehlerzustand mit „Erneut versuchen“ statt „Noch keine Katzen“
const { loadError, reloading, reload } = useLoader(() => Promise.all([
  petsStore.fetchPets(),
  petsStore.fetchFeedingStatus(),
  petsStore.fetchMembers(),
]))

// ── Lifecycle ──
onMounted(() => {
  reload()

  // Socket-Events
  on('pet_created', handleSocketPetCreated)
  on('pet_updated', handleSocketPetUpdated)
  on('pet_deleted', handleSocketPetDeleted)
  on('feeding_created', handleSocketFeedingCreated)
  on('feeding_deleted', handleSocketFeedingDeleted)
  onReconnect(handleReconnect)
})

onUnmounted(() => {
  off('pet_created', handleSocketPetCreated)
  off('pet_updated', handleSocketPetUpdated)
  off('pet_deleted', handleSocketPetDeleted)
  off('feeding_created', handleSocketFeedingCreated)
  off('feeding_deleted', handleSocketFeedingDeleted)
  offReconnect(handleReconnect)
})

// ── Socket-Handlers ──
function handleSocketPetCreated(data: Pet) {
  petsStore.handlePetCreated(data)
  petsStore.fetchFeedingStatus()
}

function handleSocketPetUpdated(data: Pet) {
  petsStore.handlePetUpdated(data)
}

function handleSocketPetDeleted(data: { id: string }) {
  petsStore.handlePetDeleted(data)
}

function handleSocketFeedingCreated(data: FeedingLog) {
  petsStore.handleFeedingCreated(data)
}

function handleSocketFeedingDeleted(data: { id: string; pet_id: string }) {
  petsStore.handleFeedingDeleted(data)
}

function handleReconnect() {
  reload()
}

// Haushaltswechsel: Daten des neuen Haushalts laden (App.vue hat den Store geleert)
watch(() => authStore.currentHouseholdId, (id) => {
  if (!id) return
  reload()
})

// ── Aktive / archivierte Tiere (PD-P2) ──
const visiblePets = computed(() => activePets(petsStore.pets))
const archivedList = computed(() => archivedPets(petsStore.pets))
const showArchive = ref(false)

function handleUnarchive(pet: Pet) {
  return run(() => petsStore.unarchivePet(pet.id), {
    key: `unarchive-${pet.id}`,
    success: t('pets.unarchived', { name: pet.name }),
    error: t('pets.updateError'),
  })
}

// ── Current Slot ──
const currentSlot = computed<FeedingSlot>(() => {
  const hour = new Date().getHours()
  return hour < 14 ? 'morning' : 'evening'
})

// ── Feeding Status Helpers ──
function getMemberName(userId: string): string {
  const member = petsStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

function formatFeedingTime(fedAt: string): string {
  const d = new Date(fedAt)
  return d.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
}

function feedingStatusText(petId: string): string {
  const status = petsStore.feedingStatus.find(s => s.pet_id === petId)
  if (!status) return t('pets.notFedYet')

  const parts: string[] = []
  if (status.morning) {
    parts.push(t('pets.fedAt', {
      slot: t('pets.morning'),
      time: formatFeedingTime(status.morning.fed_at),
      name: getMemberName(status.morning.fed_by_user_id),
    }))
  }
  if (status.evening) {
    parts.push(t('pets.fedAt', {
      slot: t('pets.evening'),
      time: formatFeedingTime(status.evening.fed_at),
      name: getMemberName(status.evening.fed_by_user_id),
    }))
  }

  return parts.length > 0 ? parts.join(' · ') : t('pets.notFedYet')
}

function isFed(petId: string, slot: FeedingSlot): boolean {
  const status = petsStore.feedingStatus.find(s => s.pet_id === petId)
  if (!status) return false
  return !!status[slot]
}

// ── "Alle als gefüttert markieren" ──
const showFeedAllButton = computed(() => {
  const slot = currentSlot.value
  return petsStore.feedingStatus.some(s => !s[slot])
})

function handleFeedAll() {
  return run(async () => {
    const result = await petsStore.feedAll(currentSlot.value)
    // „Alle gefüttert“ nur, wenn der neu geladene Status das bestätigt (CASA-13)
    if (!result.allFed) notifyInfo(t('pets.notAllFed', { fed: result.fed, total: result.total }))
    // Jemand anderes war schneller: Hinweis statt Erfolg
    else if (result.created.length === 0) notifyInfo(t('pets.allAlreadyFed'))
    return result
  }, {
    key: 'feed-all',
    success: (result) => (result.allFed && result.created.length > 0 ? t('pets.allFedToast') : undefined),
    undo: (result) => petsStore.undoFeedings(result.created),
    error: t('pets.feedError'),
  })
}

// ── Toggle Feeding ──
// Fütterung einer anderen Person entfernen → erst nachfragen (wer, wann; CASA-30)
const unfeedConfirm = ref<{ petId: string; slot: FeedingSlot; petName: string; text: string } | null>(null)

function handleToggleFeeding(petId: string, slot: FeedingSlot, petName: string) {
  const existing = petsStore.feedingStatus.find(s => s.pet_id === petId)?.[slot]
  if (existing && needsUnfeedConfirmation(existing, authStore.user?.id)) {
    unfeedConfirm.value = {
      petId, slot, petName,
      text: t('pets.unfeedOtherHint', {
        name: getMemberName(existing.fed_by_user_id),
        time: formatClock(existing.fed_at),
        pet: petName,
      }),
    }
    return
  }
  return toggleFeeding(petId, slot, petName)
}

function confirmUnfeed() {
  const pending = unfeedConfirm.value
  unfeedConfirm.value = null
  if (pending) return toggleFeeding(pending.petId, pending.slot, pending.petName)
}

function toggleFeeding(petId: string, slot: FeedingSlot, petName: string) {
  return run(async () => {
    const result = await petsStore.toggleFeeding(petId, slot)
    // 409: schon gefüttert (Status wurde neu geladen) → Hinweis, kein Fehler
    if (result === 'duplicate') notifyInfo(t('errors.FEEDING_DUPLICATE'))
    return result
  }, {
    key: `feed-${petId}-${slot}`,
    // Nur fürs Füttern; Entfernen ist selbst schon das Rückgängigmachen
    success: (result) => (result === 'fed' ? t('pets.fedToast', { name: petName }) : undefined),
    undo: () => petsStore.toggleFeeding(petId, slot),
    error: t('pets.feedError'),
  })
}

// ── Pet Card Helpers ──
function speciesEmoji(species: string): string {
  switch (species) {
    case 'cat': return '🐱'
    case 'dog': return '🐶'
    case 'bird': return '🐦'
    case 'fish': return '🐟'
    case 'rabbit': return '🐰'
    default: return '🐾'
  }
}

function calculateAge(birthdate: string | null): string | null {
  if (!birthdate) return null
  const birth = new Date(birthdate)
  const now = new Date()
  let age = now.getFullYear() - birth.getFullYear()
  if (now.getMonth() < birth.getMonth() ||
    (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate())) {
    age--
  }
  return t('pets.age', { n: age })
}

function formatWeight(grams: number | null): string | null {
  if (!grams) return null
  return t('pets.weightKg', { n: (grams / 1000).toFixed(1) })
}

// ── Add Pet Dialog ──
const showAddDialog = ref(false)
const formName = ref('')
const formBreed = ref('')
const formBirthdate = ref('')
const formWeightGrams = ref('')
const formNotes = ref('')
const formSaving = computed(() => isPending('create'))
// Inline-Fehler am Gewichtsfeld
const formWeightError = ref('')

watch(formWeightGrams, () => { formWeightError.value = '' })

function resetForm() {
  formName.value = ''
  formBreed.value = ''
  formBirthdate.value = ''
  formWeightGrams.value = ''
  formNotes.value = ''
  formWeightError.value = ''
}

function openAddDialog() {
  resetForm()
  showAddDialog.value = true
}

function closeAddDialog() {
  showAddDialog.value = false
}

async function handleCreatePet() {
  const name = formName.value.trim()
  if (!name) return

  const weightResult = parseWeightKgToGrams(formWeightGrams.value)
  if (weightResult === null) {
    formWeightError.value = t('pets.invalidWeight')
    return
  }

  const payload: PetCreatePayload = {
    name,
    breed: formBreed.value.trim() || undefined,
    birthdate: formBirthdate.value || undefined,
    weight_grams: weightResult,
    notes: formNotes.value.trim() || undefined,
  }
  const ok = await run(() => petsStore.createPet(payload), {
    key: 'create',
    success: t('pets.created'),
    error: t('pets.createError'),
  })
  if (ok) showAddDialog.value = false
}

// ── Delete / Archive Pet ──
// Vor dem endgültigen Löschen den Verlauf zählen und „Archivieren“ anbieten (PD-P2):
// Löschen entfernt alle Fütterungen, Medikamentengaben und Pflegeaufgaben unwiderruflich.
const deletingPetId = ref<string | null>(null)
const deleteHistory = ref<PetHistory | null>(null)
const deleteHistoryLoading = ref(false)
const deleteHistoryFailed = ref(false)
const deletingPet = computed(() => petsStore.pets.find(p => p.id === deletingPetId.value) ?? null)
// Verlauf unbekannt (Laden gescheitert) → vorsichtshalber wie „mit Verlauf“ behandeln
const deleteHasHistory = computed(() => deleteHistoryFailed.value || hasHistory(deleteHistory.value))

async function confirmDelete(petId: string) {
  deletingPetId.value = petId
  deleteHistory.value = null
  deleteHistoryFailed.value = false
  deleteHistoryLoading.value = true
  try {
    const history = await petsStore.fetchPetHistory(petId)
    if (deletingPetId.value === petId) deleteHistory.value = history ?? null
  } catch {
    if (deletingPetId.value === petId) deleteHistoryFailed.value = true
  } finally {
    if (deletingPetId.value === petId) deleteHistoryLoading.value = false
  }
}

function cancelDelete() {
  deletingPetId.value = null
}

async function handleDelete() {
  const id = deletingPetId.value
  if (!id) return
  // Mit Verlauf: der Dialog hat die Zahlen gezeigt und „Endgültig löschen“ wurde
  // ausdrücklich gewählt → force. Ohne bekannten Verlauf lehnt das Backend ab (409),
  // falls inzwischen doch etwas erfasst wurde — dann zeigt der Dialog die Zahlen.
  const force = deleteHasHistory.value
  let conflict: PetHistory | null = null
  const ok = await run(async () => {
    try {
      await petsStore.removePet(id, { force })
      return true
    } catch (err) {
      conflict = petHistoryConflict(err)
      if (!conflict) throw err
      return false
    }
  }, {
    key: 'delete',
    success: (deleted) => (deleted ? t('pets.deleted') : undefined),
    error: t('pets.deleteError'),
  })
  if (conflict) deleteHistory.value = conflict
  else if (ok) deletingPetId.value = null
}

async function handleArchive() {
  const pet = deletingPet.value
  if (!pet) return
  const ok = await run(() => petsStore.archivePet(pet.id), {
    key: 'archive',
    success: t('pets.archived', { name: pet.name }),
    undo: () => petsStore.unarchivePet(pet.id),
    error: t('pets.updateError'),
  })
  if (ok) deletingPetId.value = null
}

// ── Navigate to Detail ──
function navigateToPet(petId: string) {
  router.push(`/pets/${petId}`)
}
</script>

<template>
  <div class="view-page view-page--fab">
    <PageHeader :title="$t('pets.title')" />

    <!-- Loading -->
    <div v-if="petsStore.loading && petsStore.pets.length === 0" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="40px" height="40px" rounded />
        <div style="flex: 1; display: flex; flex-direction: column; gap: var(--space-1);">
          <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
          <BaseSkeleton width="40%" height="12px" />
        </div>
      </div>
    </div>

    <!-- Ladefehler (vor dem Leerzustand) -->
    <BaseErrorState
      v-else-if="loadError && petsStore.pets.length === 0"
      :retrying="reloading"
      @retry="reload"
    />

    <!-- Empty State -->
    <BaseEmptyState
      v-else-if="petsStore.pets.length === 0"
      :icon="PhCat"
      :title="$t('pets.emptyState')"
      :subtitle="$t('pets.emptyStateHint')"
    >
      <template #action>
        <BaseButton variant="primary" size="sm" @click="openAddDialog">
          {{ $t('pets.addPet') }}
        </BaseButton>
      </template>
    </BaseEmptyState>

    <template v-else>
      <!-- ═══ Fütterung heute ═══ (nur aktive Tiere) -->
      <section v-if="petsStore.feedingStatus.length > 0" class="section">
        <BaseCard>
          <h2 class="card-title">{{ $t('pets.feedingToday') }}</h2>

          <ul class="feeding-list">
            <li
              v-for="status in petsStore.feedingStatus"
              :key="status.pet_id"
              class="feeding-row"
            >
              <div class="feeding-row__info">
                <span class="feeding-row__name">{{ status.pet_name }}</span>
                <span
                  class="feeding-row__status"
                  :class="{ 'feeding-row__status--empty': !status.morning && !status.evening }"
                >
                  {{ feedingStatusText(status.pet_id) }}
                </span>
              </div>
              <div class="feeding-row__toggles">
                <button
                  type="button"
                  class="feed-toggle tap-target"
                  :class="{ 'feed-toggle--fed': isFed(status.pet_id, 'morning') }"
                  :title="$t('pets.feedToggleMorning', { name: status.pet_name })"
                  :aria-label="$t('pets.feedToggleMorning', { name: status.pet_name })"
                  :aria-pressed="isFed(status.pet_id, 'morning')"
                  @click="handleToggleFeeding(status.pet_id, 'morning', status.pet_name)"
                >
                  <PhSun :size="16" weight="bold" />
                </button>
                <button
                  type="button"
                  class="feed-toggle tap-target"
                  :class="{ 'feed-toggle--fed': isFed(status.pet_id, 'evening') }"
                  :title="$t('pets.feedToggleEvening', { name: status.pet_name })"
                  :aria-label="$t('pets.feedToggleEvening', { name: status.pet_name })"
                  :aria-pressed="isFed(status.pet_id, 'evening')"
                  @click="handleToggleFeeding(status.pet_id, 'evening', status.pet_name)"
                >
                  <PhMoon :size="16" weight="bold" />
                </button>
              </div>
            </li>
          </ul>

          <BaseButton
            v-if="showFeedAllButton"
            variant="secondary"
            size="sm"
            class="feed-all-btn"
            :loading="isPending('feed-all')"
            @click="handleFeedAll"
          >
            {{ $t('pets.markAllFed') }}
          </BaseButton>
        </BaseCard>
      </section>

      <!-- ═══ Tier-Karten ═══ -->
      <section class="section">
        <div
          v-for="pet in visiblePets"
          :key="pet.id"
          class="pet-card"
          role="button"
          tabindex="0"
          @click="navigateToPet(pet.id)"
          @keydown.enter.self="navigateToPet(pet.id)"
          @keydown.space.self.prevent="navigateToPet(pet.id)"
        >
          <div class="pet-card__header">
            <PetPhotoAvatar
              v-if="pet.photo_file_id"
              :photo-file-id="pet.photo_file_id"
              :pet-name="pet.name"
              size="sm"
            />
            <span v-else class="pet-card__emoji">{{ speciesEmoji(pet.species) }}</span>
            <span class="pet-card__name">{{ pet.name }}</span>
          </div>
          <div class="pet-card__details">
            <span>{{ pet.breed ?? $t('pets.unknownBreed') }}</span>
            <span v-if="calculateAge(pet.birthdate)"> · {{ calculateAge(pet.birthdate) }}</span>
          </div>
          <div v-if="pet.weight_grams" class="pet-card__weight">
            {{ formatWeight(pet.weight_grams) }}
          </div>
          <div class="pet-card__actions">
            <button
              class="pet-card__delete tap-target"
              @click.stop="confirmDelete(pet.id)"
              :aria-label="$t('common.delete')"
            >
              {{ $t('common.delete') }}
            </button>
          </div>
        </div>
      </section>

      <!-- ═══ Archiv (verstorben/abgegeben) ═══ -->
      <section v-if="archivedList.length > 0" class="section">
        <button
          type="button"
          class="archive-toggle tap-target"
          :aria-expanded="showArchive"
          @click="showArchive = !showArchive"
        >
          {{ $t('pets.archiveSection', { n: archivedList.length }) }}
        </button>
        <ul v-if="showArchive" class="archive-list">
          <li v-for="pet in archivedList" :key="pet.id" class="archive-row">
            <button type="button" class="archive-row__name tap-target" @click="navigateToPet(pet.id)">
              {{ pet.name }}
            </button>
            <button
              type="button"
              class="archive-row__action tap-target"
              :disabled="isPending(`unarchive-${pet.id}`)"
              @click="handleUnarchive(pet)"
            >
              {{ $t('pets.unarchive') }}
            </button>
            <button
              type="button"
              class="pet-card__delete tap-target"
              :aria-label="$t('common.delete')"
              @click="confirmDelete(pet.id)"
            >
              {{ $t('common.delete') }}
            </button>
          </li>
        </ul>
      </section>
    </template>

    <!-- FAB: Add Pet -->
    <button class="fab" @click="openAddDialog" :aria-label="$t('pets.addPet')">
      <PhPlus :size="24" weight="bold" />
    </button>

    <!-- Add Pet Dialog -->
    <BaseDialog :open="showAddDialog" :title="$t('pets.addPet')" @close="closeAddDialog">
      <form id="pet-add-form" class="dialog-form" @submit.prevent="handleCreatePet">
        <BaseInput
          v-model="formName"
          :label="$t('pets.name')"
          :placeholder="$t('pets.name')"
        />
        <BaseInput
          v-model="formBreed"
          :label="$t('pets.breed')"
          :placeholder="$t('pets.breed')"
        />
        <BaseInput
          v-model="formBirthdate"
          :label="$t('pets.birthdate')"
          type="date"
        />
        <BaseInput
          v-model="formWeightGrams"
          :label="$t('pets.weight')"
          :placeholder="$t('pets.weightPlaceholder')"
          :error="formWeightError || undefined"
          type="text"
          inputmode="decimal"
        />
        <BaseInput
          v-model="formNotes"
          :label="$t('pets.notes')"
          :placeholder="$t('pets.notes')"
        />
      </form>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="closeAddDialog">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            type="submit"
            form="pet-add-form"
            :disabled="!formName.trim() || formSaving"
            :loading="formSaving"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- Fütterung einer anderen Person entfernen (CASA-30) -->
    <BaseDialog :open="!!unfeedConfirm" :title="$t('pets.unfeedOtherTitle')" @close="unfeedConfirm = null">
      <p class="delete-hint">{{ unfeedConfirm?.text }}</p>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="unfeedConfirm = null">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton variant="danger" @click="confirmUnfeed">
            {{ $t('pets.unfeedOtherConfirm') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- Delete Confirm Dialog -->
    <BaseDialog :open="!!deletingPetId" :title="$t('pets.deleteConfirm')" danger @close="cancelDelete">
      <p v-if="deleteHistoryLoading" class="delete-hint">{{ $t('pets.historyLoading') }}</p>
      <template v-else-if="deleteHasHistory">
        <p v-if="deleteHistory" class="delete-hint delete-hint--warning">
          {{ $t('pets.deleteHistoryWarning', {
            feedings: deleteHistory.feedings,
            doses: deleteHistory.medication_logs,
            tasks: deleteHistory.care_tasks,
          }) }}
        </p>
        <p v-else class="delete-hint delete-hint--warning">{{ $t('pets.deleteHint') }}</p>
        <p v-if="deletingPet && !deletingPet.archived" class="delete-hint">{{ $t('pets.archiveHint') }}</p>
      </template>
      <p v-else class="delete-hint">{{ $t('pets.deleteNoHistory') }}</p>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="cancelDelete">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton
            v-if="deletingPet && !deletingPet.archived && deleteHasHistory"
            variant="primary"
            :loading="isPending('archive')"
            @click="handleArchive"
          >
            {{ $t('pets.archive') }}
          </BaseButton>
          <BaseButton
            variant="danger"
            :disabled="deleteHistoryLoading"
            :loading="isPending('delete')"
            @click="handleDelete"
          >
            {{ deleteHasHistory ? $t('pets.deletePermanently') : $t('common.delete') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>
  </div>
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

/* ── Feeding List ── */
.feeding-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.feeding-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line);
}

.feeding-row:last-child {
  border-bottom: none;
}

.feeding-row__info {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
  flex: 1;
}

.feeding-row__name {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.feeding-row__status {
  font-size: var(--text-xs);
  color: var(--sub);
}

.feeding-row__status--empty {
  font-style: italic;
}

.feeding-row__toggles {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ── Feed Toggle Buttons ── */
.feed-toggle {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--chip);
  color: var(--sub);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.feed-toggle:active {
  transform: scale(0.92);
}

.feed-toggle--fed {
  background: var(--ok);
  color: var(--color-on-success);
}

/* ── Feed All Button ── */
.feed-all-btn {
  margin-top: var(--space-3);
  width: 100%;
}

/* ── Pet Cards ── */
.pet-card {
  background: var(--card);
  border-radius: var(--radius-card);
  padding: var(--space-4);
  margin-bottom: var(--space-3);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: transform var(--transition-fast);
}

.pet-card:focus-visible {
  outline: 2px solid var(--acc);
  outline-offset: 2px;
}

@media (hover: hover) {
  .pet-card:hover {
    transform: scale(1.01);
  }
}

.pet-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.pet-card__emoji {
  font-size: var(--text-xl);
}

.pet-card__name {
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  font-family: var(--font-display);
}

.pet-card__details {
  font-size: var(--text-sm);
  color: var(--sub);
}

.pet-card__weight {
  font-size: var(--text-sm);
  color: var(--sub);
  margin-top: var(--space-1);
}

.pet-card__actions {
  margin-top: var(--space-2);
  display: flex;
  justify-content: flex-end;
}

/* ── Archiv ── */
.archive-toggle {
  background: none;
  border: none;
  padding: var(--space-2) 0;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  cursor: pointer;
}

.archive-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.archive-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-btn);
  background: var(--chip);
}

.archive-row__name {
  flex: 1;
  min-width: 0;
  text-align: left;
  background: none;
  border: none;
  padding: 0;
  font-size: var(--text-base);
  color: var(--sub);
  cursor: pointer;
}

.archive-row__action {
  font-size: var(--text-xs);
  color: var(--ink);
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
}

.pet-card__delete {
  font-size: var(--text-xs);
  color: var(--color-danger);
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
}

.pet-card__delete:hover {
  background: var(--chip);
}

/* ── FAB ── */
.view-page--fab {
  /* Platz, damit der FAB die letzte Karte (Löschen-Button) nicht verdeckt */
  padding-bottom: calc(var(--fab-size) + var(--space-6));
}

.fab {
  position: fixed;
  bottom: var(--fab-bottom);
  right: var(--space-4);
  width: var(--fab-size);
  height: var(--fab-size);
  border-radius: var(--radius-full);
  background: var(--acc);
  color: var(--color-on-accent);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-overlay);
  cursor: pointer;
  z-index: var(--z-fab);
  transition: transform var(--transition-fast);
}

.fab:active {
  transform: scale(0.92);
}

/* ── Dialog Form ── */
.dialog-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.delete-hint {
  font-size: var(--text-sm);
  color: var(--sub);
  margin: 0 0 var(--space-2);
}

.delete-hint--warning {
  color: var(--color-danger);
}

/* ── Skeleton ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
</style>
