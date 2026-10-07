<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { usePetsStore } from '../stores/pets'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { parseWeightKgToGrams } from '../utils/money'
import type { Pet, PetCreatePayload, FeedingSlot, FeedingLog } from '../types'
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
    const created = await petsStore.feedAll(currentSlot.value)
    // Jemand anderes war schneller: Hinweis statt Erfolg
    if (created.length === 0) notifyInfo(t('pets.allAlreadyFed'))
    return created
  }, {
    key: 'feed-all',
    success: (created) => (created.length > 0 ? t('pets.allFedToast') : undefined),
    undo: (created) => petsStore.undoFeedings(created),
    error: t('pets.feedError'),
  })
}

// ── Toggle Feeding ──
function handleToggleFeeding(petId: string, slot: FeedingSlot, petName: string) {
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

// ── Delete Pet ──
const deletingPetId = ref<string | null>(null)

function confirmDelete(petId: string) {
  deletingPetId.value = petId
}

function cancelDelete() {
  deletingPetId.value = null
}

async function handleDelete() {
  const id = deletingPetId.value
  if (!id) return
  const ok = await run(() => petsStore.removePet(id), {
    key: 'delete',
    success: t('pets.deleted'),
    error: t('pets.deleteError'),
  })
  if (ok) deletingPetId.value = null
}

// ── Navigate to Detail ──
function navigateToPet(petId: string) {
  router.push(`/pets/${petId}`)
}
</script>

<template>
  <div class="view-page">
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
      <!-- ═══ Fütterung heute ═══ -->
      <section class="section">
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
                  class="feed-toggle"
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
                  class="feed-toggle"
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
          v-for="pet in petsStore.pets"
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
              class="pet-card__delete"
              @click.stop="confirmDelete(pet.id)"
              :aria-label="$t('common.delete')"
            >
              {{ $t('common.delete') }}
            </button>
          </div>
        </div>
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

    <!-- Delete Confirm Dialog -->
    <BaseDialog :open="!!deletingPetId" :title="$t('pets.deleteConfirm')" danger @close="cancelDelete">
      <p class="delete-hint">{{ $t('pets.deleteHint') }}</p>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="cancelDelete">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton variant="danger" :loading="isPending('delete')" @click="handleDelete">
            {{ $t('common.delete') }}
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
.fab {
  position: fixed;
  bottom: calc(80px + env(safe-area-inset-bottom, 0px));
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
  margin: 0;
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
