<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { usePetsStore } from '../stores/pets'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import type {
  Pet, FeedingLog, FeedingSlot, Medication, MedicationCreatePayload,
  MedicationUpdatePayload, MedicationLog, PetUpdatePayload, HealthEntry,
} from '../types'
import {
  PhArrowLeft, PhPencilSimple, PhSun, PhMoon, PhPlus, PhPill,
  PhCheck, PhTrash,
} from '@phosphor-icons/vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'

const route = useRoute()
const router = useRouter()
const petsStore = usePetsStore()
const authStore = useAuthStore()
const { on, off, onReconnect, offReconnect } = useSocket()
const { showToast } = useToast()
const { t } = useI18n()

const petId = computed(() => route.params.id as string)
const loading = ref(true)

// ── Computed ──

const pet = computed<Pet | undefined>(() =>
  petsStore.pets.find(p => p.id === petId.value),
)

const feedingStatus = computed(() =>
  petsStore.feedingStatus.find(s => s.pet_id === petId.value),
)

const activeMedications = computed(() =>
  petsStore.medications.filter(m => m.active),
)

const inactiveMedications = computed(() =>
  petsStore.medications.filter(m => !m.active),
)

// ── Lifecycle ──

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([
      petsStore.fetchPets(),
      petsStore.fetchFeedingStatus(),
      petsStore.fetchMembers(),
      petsStore.fetchMedications(petId.value),
    ])
    // Load medication logs for all medications
    await loadAllMedicationLogs()
  } finally {
    loading.value = false
  }

  // Socket-Events
  on('pet_updated', handleSocketPetUpdated)
  on('pet_deleted', handleSocketPetDeleted)
  on('feeding_created', handleSocketFeedingCreated)
  on('feeding_deleted', handleSocketFeedingDeleted)
  on('medication_created', handleSocketMedicationCreated)
  on('medication_updated', handleSocketMedicationUpdated)
  on('medication_deleted', handleSocketMedicationDeleted)
  on('medication_given', handleSocketMedicationGiven)
  onReconnect(handleReconnect)
})

onUnmounted(() => {
  off('pet_updated', handleSocketPetUpdated)
  off('pet_deleted', handleSocketPetDeleted)
  off('feeding_created', handleSocketFeedingCreated)
  off('feeding_deleted', handleSocketFeedingDeleted)
  off('medication_created', handleSocketMedicationCreated)
  off('medication_updated', handleSocketMedicationUpdated)
  off('medication_deleted', handleSocketMedicationDeleted)
  off('medication_given', handleSocketMedicationGiven)
  offReconnect(handleReconnect)
})

async function loadAllMedicationLogs() {
  const meds = petsStore.medications
  await Promise.all(
    meds.map(m => petsStore.fetchMedicationLog(petId.value, m.id)),
  )
}

// ── Socket Handlers ──

function handleSocketPetUpdated(data: Pet) {
  petsStore.handlePetUpdated(data)
}

function handleSocketPetDeleted(data: { id: string }) {
  petsStore.handlePetDeleted(data)
  if (data.id === petId.value) {
    router.replace('/pets')
  }
}

function handleSocketFeedingCreated(data: FeedingLog) {
  petsStore.handleFeedingCreated(data)
}

function handleSocketFeedingDeleted(data: { id: string; pet_id: string }) {
  petsStore.handleFeedingDeleted(data)
}

function handleSocketMedicationCreated(med: Medication) {
  petsStore.handleMedicationCreated(med)
  if (med.pet_id === petId.value) {
    petsStore.fetchMedicationLog(petId.value, med.id)
  }
}

function handleSocketMedicationUpdated(med: Medication) {
  petsStore.handleMedicationUpdated(med)
}

function handleSocketMedicationDeleted(data: { id: string }) {
  petsStore.handleMedicationDeleted(data)
}

function handleSocketMedicationGiven(log: MedicationLog) {
  petsStore.handleMedicationGiven(log)
}

async function handleReconnect() {
  await Promise.all([
    petsStore.fetchPets(),
    petsStore.fetchFeedingStatus(),
    petsStore.fetchMedications(petId.value),
  ])
  await loadAllMedicationLogs()
}

// ── Feeding Helpers ──

function getMemberName(userId: string): string {
  const member = petsStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

function formatFeedingTime(fedAt: string): string {
  const d = new Date(fedAt)
  return d.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
}

function isFed(slot: FeedingSlot): boolean {
  if (!feedingStatus.value) return false
  return !!feedingStatus.value[slot]
}

function feedingSlotInfo(slot: FeedingSlot): string | null {
  const fs = feedingStatus.value
  if (!fs) return null
  const entry = fs[slot]
  if (!entry) return null
  return t('pets.fedAt', {
    slot: t(`pets.${slot}`),
    time: formatFeedingTime(entry.fed_at),
    name: getMemberName(entry.fed_by_user_id),
  })
}

async function handleToggleFeeding(slot: FeedingSlot) {
  try {
    await petsStore.toggleFeeding(petId.value, slot)
  } catch {
    showToast(t('pets.feedError'))
  }
}

// ── Medication Helpers ──

function isGivenToday(medicationId: string): boolean {
  const logs = petsStore.medicationLogs[medicationId]
  if (!logs || logs.length === 0) return false
  const today = new Date().toISOString().slice(0, 10)
  const lastGiven = new Date(logs[0].given_at).toISOString().slice(0, 10)
  return lastGiven === today
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

async function handleGiveMedication(medicationId: string) {
  try {
    await petsStore.giveMedication(petId.value, medicationId)
    showToast(t('pets.medicationGiven'), 'success')
  } catch {
    showToast(t('common.error'))
  }
}

// ── Add / Edit Medication Dialog ──

const showMedDialog = ref(false)
const editingMedId = ref<string | null>(null)
const medFormName = ref('')
const medFormDosage = ref('')
const medFormSchedule = ref('')
const medFormActive = ref(true)
const medSaving = ref(false)

function openAddMedDialog() {
  editingMedId.value = null
  medFormName.value = ''
  medFormDosage.value = ''
  medFormSchedule.value = ''
  medFormActive.value = true
  showMedDialog.value = true
}

function openEditMedDialog(med: Medication) {
  editingMedId.value = med.id
  medFormName.value = med.name
  medFormDosage.value = med.dosage ?? ''
  medFormSchedule.value = med.schedule ?? ''
  medFormActive.value = med.active
  showMedDialog.value = true
}

function closeMedDialog() {
  showMedDialog.value = false
}

async function handleSaveMedication() {
  const name = medFormName.value.trim()
  if (!name || medSaving.value) return

  medSaving.value = true
  try {
    if (editingMedId.value) {
      const payload: MedicationUpdatePayload = {
        name,
        dosage: medFormDosage.value.trim() || undefined,
        schedule: medFormSchedule.value.trim() || undefined,
        active: medFormActive.value,
      }
      await petsStore.updateMedication(petId.value, editingMedId.value, payload)
      showToast(t('pets.medicationUpdated'), 'success')
    } else {
      const payload: MedicationCreatePayload = {
        name,
        dosage: medFormDosage.value.trim() || undefined,
        schedule: medFormSchedule.value.trim() || undefined,
        active: medFormActive.value,
      }
      const created = await petsStore.createMedication(petId.value, payload)
      if (created) {
        await petsStore.fetchMedicationLog(petId.value, created.id)
      }
      showToast(t('pets.medicationCreated'), 'success')
    }
    showMedDialog.value = false
  } catch {
    showToast(t('common.error'))
  } finally {
    medSaving.value = false
  }
}

// ── Delete Medication ──

const deletingMedId = ref<string | null>(null)

function confirmDeleteMed(medId: string) {
  deletingMedId.value = medId
}

function cancelDeleteMed() {
  deletingMedId.value = null
}

async function handleDeleteMed() {
  if (!deletingMedId.value) return
  try {
    await petsStore.removeMedication(petId.value, deletingMedId.value)
    deletingMedId.value = null
    showToast(t('pets.medicationDeleted'), 'success')
  } catch {
    showToast(t('common.error'))
  }
}

// ── Edit Pet Dialog ──

const showEditPetDialog = ref(false)
const editFormName = ref('')
const editFormBreed = ref('')
const editFormBirthdate = ref('')
const editFormWeightGrams = ref('')
const editFormNotes = ref('')
const editFormChipNumber = ref('')
const editFormInsurance = ref('')
const editFormVetName = ref('')
const editFormFoodNotes = ref('')
const editFormHealthEntries = ref<HealthEntry[]>([])
const editPetSaving = ref(false)

function openEditPetDialog() {
  if (!pet.value) return
  editFormName.value = pet.value.name
  editFormBreed.value = pet.value.breed ?? ''
  editFormBirthdate.value = pet.value.birthdate ?? ''
  editFormWeightGrams.value = pet.value.weight_grams ? String(pet.value.weight_grams) : ''
  editFormNotes.value = pet.value.notes ?? ''
  editFormChipNumber.value = pet.value.chip_number ?? ''
  editFormInsurance.value = pet.value.insurance ?? ''
  editFormVetName.value = pet.value.vet_name ?? ''
  editFormFoodNotes.value = pet.value.food_notes ?? ''
  editFormHealthEntries.value = pet.value.health_entries
    ? pet.value.health_entries.map(e => ({ ...e }))
    : []
  showEditPetDialog.value = true
}

function closeEditPetDialog() {
  showEditPetDialog.value = false
}

function addHealthEntry() {
  editFormHealthEntries.value.push({ title: '', subtitle: '', severity: 'green' })
}

function removeHealthEntry(index: number) {
  editFormHealthEntries.value.splice(index, 1)
}

async function handleUpdatePet() {
  const name = editFormName.value.trim()
  if (!name || editPetSaving.value) return

  editPetSaving.value = true
  try {
    // Filter out empty health entries
    const validEntries = editFormHealthEntries.value.filter(e => e.title.trim())

    const payload: PetUpdatePayload = {
      name,
      breed: editFormBreed.value.trim() || undefined,
      birthdate: editFormBirthdate.value || undefined,
      weight_grams: editFormWeightGrams.value ? parseInt(editFormWeightGrams.value) : undefined,
      notes: editFormNotes.value.trim() || undefined,
      chip_number: editFormChipNumber.value.trim() || undefined,
      insurance: editFormInsurance.value.trim() || undefined,
      vet_name: editFormVetName.value.trim() || undefined,
      food_notes: editFormFoodNotes.value.trim() || undefined,
      health_entries: validEntries.length > 0 ? validEntries : undefined,
    }
    await petsStore.updatePet(petId.value, payload)
    showEditPetDialog.value = false
    showToast(t('pets.updated'), 'success')
  } catch {
    showToast(t('pets.updateError'))
  } finally {
    editPetSaving.value = false
  }
}

// ── Pet Info Helpers ──

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
</script>

<template>
  <div class="view-page">
    <!-- ═══ Loading State ═══ -->
    <div v-if="loading" class="skeleton-list">
      <BaseSkeleton width="120px" height="28px" />
      <BaseSkeleton width="100%" height="120px" />
      <BaseSkeleton width="100%" height="180px" />
      <BaseSkeleton width="100%" height="100px" />
    </div>

    <!-- ═══ Pet not found ═══ -->
    <div v-else-if="!pet" class="not-found">
      <p>{{ $t('common.error') }}</p>
      <BaseButton variant="secondary" size="sm" @click="router.push('/pets')">
        {{ $t('common.back') }}
      </BaseButton>
    </div>

    <template v-else>
      <!-- ═══ Header ═══ -->
      <div class="detail-header">
        <button class="back-btn" @click="router.back()" :aria-label="$t('common.back')">
          <PhArrowLeft :size="22" weight="bold" />
        </button>
        <div class="detail-header__info">
          <span class="detail-header__emoji">{{ speciesEmoji(pet.species) }}</span>
          <h1 class="detail-header__name">{{ pet.name }}</h1>
        </div>
        <button class="edit-btn" @click="openEditPetDialog" :aria-label="$t('common.edit')">
          <PhPencilSimple :size="20" weight="bold" />
        </button>
      </div>

      <!-- ═══ Fütterung heute ═══ -->
      <section class="section">
        <BaseCard>
          <h2 class="card-title">{{ $t('pets.feedingToday') }}</h2>

          <div class="feeding-detail">
            <div class="feeding-detail__row">
              <div class="feeding-detail__info">
                <span class="feeding-detail__slot-label">{{ $t('pets.morning') }}</span>
                <span v-if="feedingSlotInfo('morning')" class="feeding-detail__text">
                  {{ feedingSlotInfo('morning') }}
                </span>
                <span v-else class="feeding-detail__text feeding-detail__text--empty">
                  {{ $t('pets.notFedYet') }}
                </span>
              </div>
              <button
                class="feed-toggle"
                :class="{ 'feed-toggle--fed': isFed('morning') }"
                :title="$t('pets.morningShort')"
                :aria-label="$t('pets.morning')"
                @click="handleToggleFeeding('morning')"
              >
                <PhSun :size="16" weight="bold" />
              </button>
            </div>

            <div class="feeding-detail__row">
              <div class="feeding-detail__info">
                <span class="feeding-detail__slot-label">{{ $t('pets.evening') }}</span>
                <span v-if="feedingSlotInfo('evening')" class="feeding-detail__text">
                  {{ feedingSlotInfo('evening') }}
                </span>
                <span v-else class="feeding-detail__text feeding-detail__text--empty">
                  {{ $t('pets.notFedYet') }}
                </span>
              </div>
              <button
                class="feed-toggle"
                :class="{ 'feed-toggle--fed': isFed('evening') }"
                :title="$t('pets.eveningShort')"
                :aria-label="$t('pets.evening')"
                @click="handleToggleFeeding('evening')"
              >
                <PhMoon :size="16" weight="bold" />
              </button>
            </div>
          </div>
        </BaseCard>
      </section>

      <!-- ═══ Medikamente ═══ -->
      <section class="section">
        <BaseCard>
          <h2 class="card-title">{{ $t('pets.medications') }}</h2>

          <!-- Keine Medikamente -->
          <div v-if="petsStore.medications.length === 0" class="med-empty">
            <PhPill :size="32" weight="light" class="med-empty__icon" />
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
                    {{ isGivenToday(med.id) ? $t('pets.givenToday') : $t('pets.notGivenToday') }}
                  </span>
                </div>
                <div class="med-item__actions">
                  <button
                    class="med-action-btn med-action-btn--edit"
                    @click="openEditMedDialog(med)"
                    :aria-label="$t('common.edit')"
                  >
                    <PhPencilSimple :size="16" />
                  </button>
                  <button
                    class="med-action-btn med-action-btn--delete"
                    @click="confirmDeleteMed(med.id)"
                    :aria-label="$t('common.delete')"
                  >
                    <PhTrash :size="16" />
                  </button>
                </div>
              </div>

              <!-- Give Button -->
              <BaseButton
                v-if="!isGivenToday(med.id)"
                variant="primary"
                size="sm"
                class="med-give-btn"
                @click="handleGiveMedication(med.id)"
              >
                {{ $t('pets.giveNow') }}
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
                    <span class="med-log__user">👤 {{ getMemberName(log.given_by_user_id) }}</span>
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
                      class="med-action-btn med-action-btn--edit"
                      @click="openEditMedDialog(med)"
                      :aria-label="$t('common.edit')"
                    >
                      <PhPencilSimple :size="16" />
                    </button>
                    <button
                      class="med-action-btn med-action-btn--delete"
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

      <!-- ═══ Über {Name} ═══ -->
      <section class="section">
        <BaseCard>
          <h2 class="card-title">{{ $t('pets.about', { name: pet.name }) }}</h2>

          <div class="fact-list">
            <div v-if="pet.breed" class="fact-row">
              <span class="fact-label">{{ $t('pets.breed') }}</span>
              <span class="fact-value">{{ pet.breed }}</span>
            </div>
            <div v-if="calculateAge(pet.birthdate)" class="fact-row">
              <span class="fact-label">{{ $t('pets.birthdateLabel') }}</span>
              <span class="fact-value">{{ calculateAge(pet.birthdate) }}</span>
            </div>
            <div v-if="pet.weight_grams" class="fact-row">
              <span class="fact-label">{{ $t('pets.weight') }}</span>
              <span class="fact-value">{{ (pet.weight_grams / 1000).toFixed(1) }} kg</span>
            </div>
            <div v-if="pet.chip_number" class="fact-row">
              <span class="fact-label">{{ $t('pets.chipNumber') }}</span>
              <span class="fact-value">{{ pet.chip_number }}</span>
            </div>
            <div v-if="pet.insurance" class="fact-row">
              <span class="fact-label">{{ $t('pets.insurance') }}</span>
              <span class="fact-value">{{ pet.insurance }}</span>
            </div>
            <div v-if="pet.vet_name" class="fact-row">
              <span class="fact-label">{{ $t('pets.vetName') }}</span>
              <span class="fact-value">{{ pet.vet_name }}</span>
            </div>
            <div v-if="pet.food_notes" class="fact-row">
              <span class="fact-label">{{ $t('pets.foodNotes') }}</span>
              <span class="fact-value">{{ pet.food_notes }}</span>
            </div>
            <div v-if="pet.notes" class="fact-row">
              <span class="fact-label">{{ $t('pets.notes') }}</span>
              <span class="fact-value">{{ pet.notes }}</span>
            </div>
          </div>

          <!-- Gesundheitseinträge -->
          <div v-if="pet.health_entries?.length" class="health-section">
            <h4 class="health-title">{{ $t('pets.health') }}</h4>
            <div v-for="(entry, i) in pet.health_entries" :key="i" class="health-entry">
              <span class="health-dot" :class="'health-dot--' + entry.severity" />
              <div class="health-text">
                <span class="health-entry-title">{{ entry.title }}</span>
                <span class="health-entry-subtitle">{{ entry.subtitle }}</span>
              </div>
            </div>
          </div>
        </BaseCard>
      </section>
    </template>

    <!-- ═══ Add / Edit Medication Dialog ═══ -->
    <BaseDialog
      :open="showMedDialog"
      :title="editingMedId ? $t('pets.editMedication') : $t('pets.addMedication')"
      @close="closeMedDialog"
    >
      <form class="dialog-form" @submit.prevent="handleSaveMedication">
        <BaseInput
          v-model="medFormName"
          :label="$t('pets.medicationName')"
          :placeholder="$t('pets.medicationName')"
        />
        <BaseInput
          v-model="medFormDosage"
          :label="$t('pets.medicationDosage')"
          :placeholder="$t('pets.medicationDosage')"
        />
        <BaseInput
          v-model="medFormSchedule"
          :label="$t('pets.medicationSchedule')"
          :placeholder="$t('pets.medicationSchedule')"
        />
        <label class="checkbox-row">
          <input
            type="checkbox"
            v-model="medFormActive"
            class="checkbox-row__input"
          />
          <span class="checkbox-row__label">{{ $t('pets.medicationActive') }}</span>
        </label>
      </form>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="closeMedDialog">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            :disabled="!medFormName.trim() || medSaving"
            :loading="medSaving"
            @click="handleSaveMedication"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ═══ Delete Medication Confirm ═══ -->
    <BaseDialog
      :open="!!deletingMedId"
      :title="$t('pets.deleteMedicationConfirm')"
      danger
      @close="cancelDeleteMed"
    >
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="cancelDeleteMed">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton variant="danger" @click="handleDeleteMed">
            {{ $t('common.delete') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ═══ Edit Pet Dialog ═══ -->
    <BaseDialog
      :open="showEditPetDialog"
      :title="$t('pets.editPet')"
      @close="closeEditPetDialog"
    >
      <form class="dialog-form" @submit.prevent="handleUpdatePet">
        <BaseInput
          v-model="editFormName"
          :label="$t('pets.name')"
          :placeholder="$t('pets.name')"
        />
        <BaseInput
          v-model="editFormBreed"
          :label="$t('pets.breed')"
          :placeholder="$t('pets.breed')"
        />
        <BaseInput
          v-model="editFormBirthdate"
          :label="$t('pets.birthdate')"
          type="date"
        />
        <BaseInput
          v-model="editFormWeightGrams"
          :label="$t('pets.weight')"
          :placeholder="$t('pets.weight')"
          type="number"
        />
        <BaseInput
          v-model="editFormChipNumber"
          :label="$t('pets.chipNumber')"
          :placeholder="$t('pets.chipNumber')"
        />
        <BaseInput
          v-model="editFormInsurance"
          :label="$t('pets.insurance')"
          :placeholder="$t('pets.insurance')"
        />
        <BaseInput
          v-model="editFormVetName"
          :label="$t('pets.vetName')"
          :placeholder="$t('pets.vetName')"
        />
        <BaseInput
          v-model="editFormFoodNotes"
          :label="$t('pets.foodNotes')"
          :placeholder="$t('pets.foodNotes')"
        />
        <BaseInput
          v-model="editFormNotes"
          :label="$t('pets.notes')"
          :placeholder="$t('pets.notes')"
        />

        <!-- Health Entries Editor -->
        <div class="health-editor">
          <label class="health-editor__label">{{ $t('pets.health') }}</label>
          <div
            v-for="(entry, i) in editFormHealthEntries"
            :key="i"
            class="health-editor__row"
          >
            <div class="health-editor__severity">
              <button
                type="button"
                class="severity-btn severity-btn--green"
                :class="{ 'severity-btn--active': entry.severity === 'green' }"
                @click="entry.severity = 'green'"
                :title="$t('pets.severityGreen')"
              />
              <button
                type="button"
                class="severity-btn severity-btn--yellow"
                :class="{ 'severity-btn--active': entry.severity === 'yellow' }"
                @click="entry.severity = 'yellow'"
                :title="$t('pets.severityYellow')"
              />
              <button
                type="button"
                class="severity-btn severity-btn--red"
                :class="{ 'severity-btn--active': entry.severity === 'red' }"
                @click="entry.severity = 'red'"
                :title="$t('pets.severityRed')"
              />
            </div>
            <div class="health-editor__fields">
              <input
                v-model="entry.title"
                class="health-editor__input"
                :placeholder="$t('pets.healthTitle')"
              />
              <input
                v-model="entry.subtitle"
                class="health-editor__input"
                :placeholder="$t('pets.healthSubtitle')"
              />
            </div>
            <button
              type="button"
              class="health-editor__delete"
              @click="removeHealthEntry(i)"
              :aria-label="$t('common.delete')"
            >
              <PhTrash :size="16" />
            </button>
          </div>
          <button
            type="button"
            class="health-editor__add"
            @click="addHealthEntry"
          >
            <PhPlus :size="14" weight="bold" />
            {{ $t('pets.addHealthEntry') }}
          </button>
        </div>
      </form>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="closeEditPetDialog">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            :disabled="!editFormName.trim() || editPetSaving"
            :loading="editPetSaving"
            @click="handleUpdatePet"
          >
            {{ $t('common.save') }}
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
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-3) 0;
  color: var(--ink);
}

/* ── Header ── */
.detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.back-btn,
.edit-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
}

.back-btn:hover,
.edit-btn:hover {
  color: var(--ink);
  background: var(--chip);
}

.detail-header__info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.detail-header__emoji {
  font-size: var(--text-xl);
}

.detail-header__name {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Feeding Detail ── */
.feeding-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.feeding-detail__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line);
}

.feeding-detail__row:last-child {
  border-bottom: none;
}

.feeding-detail__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.feeding-detail__slot-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.feeding-detail__text {
  font-size: var(--text-xs);
  color: var(--sub);
}

.feeding-detail__text--empty {
  font-style: italic;
}

/* ── Feed Toggle Buttons (reused from PetsView) ── */
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
  flex-shrink: 0;
}

.feed-toggle:active {
  transform: scale(0.92);
}

.feed-toggle--fed {
  background: var(--ok);
  color: #fff;
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
  margin-top: 2px;
  font-size: 10px;
  color: var(--sub);
}

.med-check--given {
  background: var(--ok);
  border-color: var(--ok);
  color: #fff;
}

.med-check--inactive {
  border-color: var(--sub);
  color: var(--sub);
  font-size: 8px;
}

.med-item__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.med-item__name {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.med-item__badge {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-normal);
  color: var(--sub);
  background: var(--chip);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
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
  color: var(--warn, var(--sub));
}

.med-item__actions {
  display: flex;
  gap: var(--space-1);
  flex-shrink: 0;
}

.med-action-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-1);
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
  gap: 4px;
}

.med-log__entry {
  font-size: var(--text-xs);
  color: var(--sub);
  display: flex;
  gap: var(--space-2);
}

.med-log__user {
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

/* ── Fact List ── */
.fact-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.fact-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--line);
}

.fact-row:last-child {
  border-bottom: none;
}

.fact-label {
  font-size: var(--text-sm);
  color: var(--sub);
  font-weight: var(--font-weight-medium);
  flex-shrink: 0;
}

.fact-value {
  font-size: var(--text-sm);
  color: var(--ink);
  text-align: right;
  word-break: break-word;
}

/* ── Health Section ── */
.health-section {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--line);
}

.health-title {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0 0 var(--space-3) 0;
}

.health-entry {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) 0;
}

.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 5px;
}

.health-dot--green { background: var(--ok); }
.health-dot--yellow { background: var(--color-warning, #f59e0b); }
.health-dot--red { background: var(--color-danger, #ef4444); }

.health-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.health-entry-title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.health-entry-subtitle {
  font-size: var(--text-xs);
  color: var(--sub);
}

/* ── Health Editor (Edit Dialog) ── */
.health-editor {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.health-editor__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.health-editor__row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2);
  background: var(--chip);
  border-radius: var(--radius-sm);
}

.health-editor__severity {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 4px;
}

.severity-btn {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  opacity: 0.35;
  transition: opacity var(--transition-fast), border-color var(--transition-fast);
}

.severity-btn:hover {
  opacity: 0.7;
}

.severity-btn--active {
  opacity: 1;
  border-color: var(--ink);
}

.severity-btn--green { background: var(--ok); }
.severity-btn--yellow { background: var(--color-warning, #f59e0b); }
.severity-btn--red { background: var(--color-danger, #ef4444); }

.health-editor__fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.health-editor__input {
  width: 100%;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--ink);
  background: var(--surface);
}

.health-editor__input::placeholder {
  color: var(--sub);
}

.health-editor__delete {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
}

.health-editor__delete:hover {
  color: var(--color-danger, #ef4444);
  background: var(--chip);
}

.health-editor__add {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  background: none;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-sm);
  cursor: pointer;
  padding: var(--space-2);
  color: var(--sub);
  font-size: var(--text-sm);
  transition: color var(--transition-fast), border-color var(--transition-fast);
}

.health-editor__add:hover {
  color: var(--ink);
  border-color: var(--ink);
}

/* ── Not Found ── */
.not-found {
  text-align: center;
  padding: var(--space-8) 0;
  color: var(--sub);
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

/* ── Checkbox Row ── */
.checkbox-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.checkbox-row__input {
  width: 18px;
  height: 18px;
  accent-color: var(--acc);
  cursor: pointer;
}

.checkbox-row__label {
  font-size: var(--text-sm);
  color: var(--ink);
}

/* ── Skeleton ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
