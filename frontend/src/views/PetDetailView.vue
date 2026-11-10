<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePetsStore } from '../stores/pets'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import type { Pet, FeedingLog, Medication, MedicationLog, PetCareTask } from '../types'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import PetProfileHeader from '../components/pets/PetProfileHeader.vue'
import PetEditDialog from '../components/pets/PetEditDialog.vue'
import PetFeedingCard from '../components/pets/PetFeedingCard.vue'
import PetMedicationsCard from '../components/pets/PetMedicationsCard.vue'
import PetCareTasksSection from '../components/pets/PetCareTasksSection.vue'
import PetAboutCard from '../components/pets/PetAboutCard.vue'

const route = useRoute()
const router = useRouter()
const petsStore = usePetsStore()
const authStore = useAuthStore()
const { on, off, onReconnect, offReconnect } = useSocket()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const petId = computed(() => route.params.id as string)
// Erst nach dem ersten Ladeversuch „nicht gefunden“ oder Fehler zeigen
const loaded = ref(false)

// ── Computed ──

const pet = computed<Pet | undefined>(() =>
  petsStore.pets.find(p => p.id === petId.value),
)

const householdId = computed(() => authStore.currentHouseholdId)

// Bearbeiten-Dialog (geöffnet über den Stift im Kopf)
const showEditPetDialog = ref(false)

// ── Lifecycle ──

async function loadAll() {
  const id = petId.value
  const hid = householdId.value
  await Promise.all([
    petsStore.fetchPets(),
    petsStore.fetchFeedingStatus(),
    petsStore.fetchMembers(),
    petsStore.fetchMedications(id),
    petsStore.fetchCareTasks(id),
  ])
  // Load medication logs for all medications
  if (petId.value === id && householdId.value === hid) await loadAllMedicationLogs(id)
}

// Ladefehler → Fehlerzustand mit „Erneut versuchen“ (statt „nicht gefunden“)
const { loadError, reloading, reload } = useLoader(loadAll)

onMounted(async () => {
  await reload()
  loaded.value = true

  // Socket-Events
  on('pet_updated', handleSocketPetUpdated)
  on('pet_deleted', handleSocketPetDeleted)
  on('feeding_created', handleSocketFeedingCreated)
  on('feeding_deleted', handleSocketFeedingDeleted)
  on('medication_created', handleSocketMedicationCreated)
  on('medication_updated', handleSocketMedicationUpdated)
  on('medication_deleted', handleSocketMedicationDeleted)
  on('medication_given', handleSocketMedicationGiven)
  on('pet_care_task_created', handleSocketCareTaskCreated)
  on('pet_care_task_updated', handleSocketCareTaskUpdated)
  on('pet_care_task_deleted', handleSocketCareTaskDeleted)
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
  off('pet_care_task_created', handleSocketCareTaskCreated)
  off('pet_care_task_updated', handleSocketCareTaskUpdated)
  off('pet_care_task_deleted', handleSocketCareTaskDeleted)
  offReconnect(handleReconnect)
})

// Wechsel zu einem anderen Tier (z. B. über Push-Link): Listen leert der Store, hier neu laden
watch([petId, householdId], () => {
  reload()
})

async function loadAllMedicationLogs(id = petId.value) {
  const meds = petsStore.medications
  await Promise.all(
    meds.map(m => petsStore.fetchMedicationLog(id, m.id)),
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

function handleSocketCareTaskCreated(task: PetCareTask) {
  petsStore.handleCareTaskCreated(task)
}

function handleSocketCareTaskUpdated(task: PetCareTask) {
  petsStore.handleCareTaskUpdated(task)
}

function handleSocketCareTaskDeleted(data: { id: string }) {
  petsStore.handleCareTaskDeleted(data)
}

function handleReconnect() {
  reload()
}

// ── Archiv (PD-P2) ──

function handleArchivePet() {
  const current = pet.value
  if (!current) return
  return run(() => petsStore.archivePet(current.id), {
    key: 'archive',
    success: t('pets.archived', { name: current.name }),
    undo: () => petsStore.unarchivePet(current.id),
    error: t('pets.updateError'),
  })
}

function handleUnarchivePet() {
  const current = pet.value
  if (!current) return
  return run(() => petsStore.unarchivePet(current.id), {
    key: 'archive',
    success: t('pets.unarchived', { name: current.name }),
    error: t('pets.updateError'),
  })
}
</script>

<template>
  <div class="view-page">
    <!-- ═══ Loading State ═══ -->
    <div v-if="!loaded || (reloading && !pet)" class="skeleton-list">
      <BaseSkeleton width="120px" height="28px" />
      <BaseSkeleton width="100%" height="120px" />
      <BaseSkeleton width="100%" height="180px" />
      <BaseSkeleton width="100%" height="100px" />
    </div>

    <!-- ═══ Ladefehler ═══ -->
    <div v-else-if="loadError && !pet">
      <BaseErrorState :retrying="reloading" @retry="reload" />
      <div class="not-found__back">
        <BaseButton variant="ghost" size="sm" @click="router.push('/pets')">
          {{ $t('common.back') }}
        </BaseButton>
      </div>
    </div>

    <!-- ═══ Pet not found ═══ -->
    <div v-else-if="!pet" class="not-found">
      <p>{{ $t('errors.PET_NOT_FOUND') }}</p>
      <BaseButton variant="secondary" size="sm" @click="router.push('/pets')">
        {{ $t('common.back') }}
      </BaseButton>
    </div>

    <template v-else>
      <!-- ═══ Foto + Header ═══ -->
      <PetProfileHeader :pet="pet" @edit="showEditPetDialog = true" />

      <!-- Teilweise nicht geladen (z. B. Medikamente/Pflege): Hinweis statt leerer Listen -->
      <BaseErrorState v-if="loadError" :retrying="reloading" @retry="reload" />

      <!-- ═══ Archiviert: Hinweis + Reaktivieren ═══ -->
      <section v-if="pet.archived" class="section">
        <BaseCard>
          <p class="archived-hint">{{ $t('pets.archivedHint') }}</p>
          <BaseButton variant="secondary" size="sm" :loading="isPending('archive')" @click="handleUnarchivePet">
            {{ $t('pets.unarchive') }}
          </BaseButton>
        </BaseCard>
      </section>

      <!-- ═══ Fütterung heute ═══ (Karte nicht für archivierte Tiere) -->
      <PetFeedingCard :pet="pet" />

      <!-- ═══ Medikamente ═══ -->
      <PetMedicationsCard :pet-id="pet.id" />

      <!-- ═══ Pflege & Termine ═══ -->
      <PetCareTasksSection :pet-id="pet.id" />

      <!-- ═══ Über {Name} ═══ -->
      <PetAboutCard :pet="pet" :archiving="isPending('archive')" @archive="handleArchivePet" />

      <!-- ═══ Edit Pet Dialog ═══ -->
      <PetEditDialog v-model="showEditPetDialog" :pet="pet" />
    </template>
  </div>
</template>

<style scoped>
/* ── Section ── */
.section {
  margin-bottom: var(--space-4);
}

.archived-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--sub);
}

/* ── Not Found ── */
.not-found {
  text-align: center;
  padding: var(--space-8) 0;
  color: var(--sub);
}

.not-found__back {
  display: flex;
  justify-content: center;
}

/* ── Skeleton ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
