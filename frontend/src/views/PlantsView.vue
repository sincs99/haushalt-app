<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { usePlantsStore } from '../stores/plants'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { careTaskName, dueText, isWaterDue, mergeCareNotes } from '../utils/plantCare'
import type { AiPlantCareAdvice, Plant, PlantCareLog, PlantCareStatus, PlantCareStatusTask } from '../types'
import { PhPlant, PhPlus, PhDrop } from '@phosphor-icons/vue'
import AiPlantCareCard from '../components/AiPlantCareCard.vue'
import PlantPhotoAvatar from '../components/PlantPhotoAvatar.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'

const plantsStore = usePlantsStore()
const router = useRouter()
const { on, off, onReconnect, offReconnect } = useSocket()
const { showToast } = useToast()
const { t } = useI18n()

// ── Lifecycle ──
onMounted(() => {
  plantsStore.fetchPlants()
  plantsStore.fetchCareStatus()

  on('plant_created', handleSocketPlantCreated)
  on('plant_updated', handleSocketPlantUpdated)
  on('plant_deleted', handleSocketPlantDeleted)
  on('plant_care_logged', handleSocketCareLogged)
  onReconnect(handleReconnect)
})

onUnmounted(() => {
  off('plant_created', handleSocketPlantCreated)
  off('plant_updated', handleSocketPlantUpdated)
  off('plant_deleted', handleSocketPlantDeleted)
  off('plant_care_logged', handleSocketCareLogged)
  offReconnect(handleReconnect)
})

// ── Socket-Handlers ──
// (Pflegeaufgaben-Events werden global in App.vue verarbeitet)
function handleSocketPlantCreated(data: Plant) {
  plantsStore.handlePlantCreated(data)
  plantsStore.fetchCareStatus()
}

function handleSocketPlantUpdated(data: Plant) {
  plantsStore.handlePlantUpdated(data)
}

function handleSocketPlantDeleted(data: { id: string }) {
  plantsStore.handlePlantDeleted(data)
}

function handleSocketCareLogged(_data: PlantCareLog) {
  // Fälligkeiten haben sich verschoben → Server-Status neu laden
  plantsStore.fetchCareStatus()
}

function handleReconnect() {
  plantsStore.fetchPlants()
  plantsStore.fetchCareStatus()
}

// ── Status-Helpers ──
function statusFor(plantId: string): PlantCareStatus | undefined {
  return plantsStore.careStatus.find(s => s.plant_id === plantId)
}

function hasWaterTask(plantId: string): boolean {
  return !!statusFor(plantId)?.tasks.some(task => task.care_type === 'water')
}

function dueTasks(plantId: string) {
  return statusFor(plantId)?.tasks.filter(task => task.due_today || task.overdue) ?? []
}

function nextTask(plantId: string) {
  return statusFor(plantId)?.tasks[0]
}

function badgeState(plantId: string): 'overdue' | 'today' | 'ok' | 'none' {
  const status = statusFor(plantId)
  if (!status || status.tasks.length === 0) return 'none'
  if (status.overdue) return 'overdue'
  if (status.due_today) return 'today'
  return 'ok'
}

const anyWaterDue = computed(() => plantsStore.careStatus.some(isWaterDue))

// ── Aktionen ──
const wateringIds = ref(new Set<string>())

async function handleWater(plantId: string) {
  if (wateringIds.value.has(plantId)) return
  wateringIds.value.add(plantId)
  try {
    await plantsStore.waterPlant(plantId)
  } catch {
    showToast(t('plants.careError'), 'error')
  } finally {
    wateringIds.value.delete(plantId)
  }
}

const wateringAll = ref(false)

async function handleWaterAll() {
  if (wateringAll.value) return
  wateringAll.value = true
  try {
    await plantsStore.waterAll()
    showToast(t('plants.waterAllDone'), 'success')
  } catch {
    showToast(t('plants.careError'), 'error')
  } finally {
    wateringAll.value = false
  }
}

// ── Add Plant Dialog ──
const showAddDialog = ref(false)
const formName = ref('')
const formSpecies = ref('')
const formLocation = ref('')
const formNotes = ref('')
const formAddWaterTask = ref(true)
const formSaving = ref(false)
// Übernommener KI-Vorschlag: wird erst beim Speichern der Pflanze angelegt
const formAdvice = ref<AiPlantCareAdvice | null>(null)

function openAddDialog() {
  formName.value = ''
  formSpecies.value = ''
  formLocation.value = ''
  formNotes.value = ''
  formAddWaterTask.value = true
  formAdvice.value = null
  showAddDialog.value = true
}

function adoptAdvice(advice: AiPlantCareAdvice) {
  formAdvice.value = advice
  if (!formSpecies.value.trim() && advice.botanical_name) formSpecies.value = advice.botanical_name.slice(0, 80)
}

function closeAddDialog() {
  showAddDialog.value = false
}

async function handleCreatePlant() {
  const name = formName.value.trim()
  if (!name || formSaving.value) return

  formSaving.value = true
  try {
    const created = await plantsStore.createPlant({
      name,
      species: formSpecies.value.trim() || undefined,
      location: formLocation.value.trim() || undefined,
      notes: formNotes.value.trim() || undefined,
      care_notes: formAdvice.value ? mergeCareNotes(null, formAdvice.value.care_notes) || undefined : undefined,
    })
    if (created && formAdvice.value) {
      try {
        await plantsStore.applyAdviceTasks(created.id, formAdvice.value)
      } catch {
        showToast(t('ai.plant.applyError'), 'error')
      }
    } else if (created && formAddWaterTask.value) {
      try {
        await plantsStore.createCareTask(created.id, { care_type: 'water' })
      } catch {
        showToast(t('plants.careError'), 'error')
      }
    }
    showAddDialog.value = false
    showToast(t('plants.created'), 'success')
  } catch {
    showToast(t('plants.createError'), 'error')
  } finally {
    formSaving.value = false
  }
}

// ── Delete Plant ──
const deletingPlantId = ref<string | null>(null)

async function handleDelete() {
  if (!deletingPlantId.value) return
  try {
    await plantsStore.removePlant(deletingPlantId.value)
    deletingPlantId.value = null
    showToast(t('plants.deleted'), 'success')
  } catch {
    showToast(t('plants.deleteError'), 'error')
  }
}

function summaryTask(plantId: string): PlantCareStatusTask | undefined {
  // Für die Kartenzeile: fällige Aufgaben zuerst, sonst die nächste anstehende
  return dueTasks(plantId)[0] ?? nextTask(plantId)
}
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('plants.title')" />

    <!-- Loading -->
    <div v-if="plantsStore.loading && plantsStore.plants.length === 0" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="40px" height="40px" rounded />
        <div style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
          <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
          <BaseSkeleton width="40%" height="12px" />
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <BaseEmptyState
      v-else-if="plantsStore.plants.length === 0"
      :icon="PhPlant"
      :title="$t('plants.emptyState')"
      :subtitle="$t('plants.emptyStateHint')"
    >
      <template #action>
        <BaseButton variant="primary" size="sm" @click="openAddDialog">
          {{ $t('plants.addPlant') }}
        </BaseButton>
      </template>
    </BaseEmptyState>

    <template v-else>
      <!-- ═══ Alle fälligen gießen ═══ -->
      <section v-if="anyWaterDue" class="section">
        <BaseCard>
          <h2 class="card-title">{{ $t('plants.overviewToday') }}</h2>
          <BaseButton
            variant="primary"
            size="sm"
            class="water-all-btn"
            :loading="wateringAll"
            :disabled="wateringAll"
            @click="handleWaterAll"
          >
            <PhDrop :size="18" weight="bold" />
            {{ $t('plants.waterAll') }}
          </BaseButton>
        </BaseCard>
      </section>

      <!-- ═══ Pflanzen-Karten ═══ -->
      <section class="section">
        <div
          v-for="plant in plantsStore.plants"
          :key="plant.id"
          class="plant-card"
          @click="router.push(`/plants/${plant.id}`)"
        >
          <div class="plant-card__header">
            <PlantPhotoAvatar :photo-file-id="plant.photo_file_id" :plant-name="plant.name" size="sm" />
            <div class="plant-card__title">
              <span class="plant-card__name">{{ plant.name }}</span>
              <span v-if="plant.species || plant.location" class="plant-card__details">
                {{ [plant.species, plant.location].filter(Boolean).join(' · ') }}
              </span>
            </div>
            <span
              v-if="badgeState(plant.id) === 'overdue'"
              class="due-badge due-badge--overdue"
            >{{ $t('plants.overdue') }}</span>
            <span
              v-else-if="badgeState(plant.id) === 'today'"
              class="due-badge due-badge--today"
            >{{ $t('plants.dueToday') }}</span>
          </div>

          <div v-if="summaryTask(plant.id)" class="plant-card__next">
            {{ careTaskName(summaryTask(plant.id)!, t) }}
            · {{ dueText(summaryTask(plant.id)!.next_due_at, t) }}
          </div>
          <div v-else class="plant-card__next plant-card__next--empty">
            {{ $t('plants.noTasksShort') }}
          </div>

          <div class="plant-card__actions">
            <button
              class="plant-card__delete"
              @click.stop="deletingPlantId = plant.id"
              :aria-label="$t('common.delete')"
            >
              {{ $t('common.delete') }}
            </button>
            <BaseButton
              v-if="hasWaterTask(plant.id)"
              :variant="badgeState(plant.id) === 'overdue' || badgeState(plant.id) === 'today' ? 'primary' : 'secondary'"
              size="sm"
              :disabled="wateringIds.has(plant.id)"
              @click.stop="handleWater(plant.id)"
            >
              <PhDrop :size="18" weight="bold" />
              {{ $t('plants.watered') }}
            </BaseButton>
          </div>
        </div>
      </section>
    </template>

    <!-- FAB: Add Plant -->
    <button class="fab" @click="openAddDialog" :aria-label="$t('plants.addPlant')">
      <PhPlus :size="24" weight="bold" />
    </button>

    <!-- Add Plant Dialog -->
    <BaseDialog :open="showAddDialog" :title="$t('plants.addPlant')" @close="closeAddDialog">
      <form class="dialog-form" @submit.prevent="handleCreatePlant">
        <BaseInput v-model="formName" :label="$t('plants.name')" :placeholder="$t('plants.name')" />
        <BaseInput v-model="formSpecies" :label="$t('plants.species')" :placeholder="$t('plants.speciesPlaceholder')" />
        <BaseInput v-model="formLocation" :label="$t('plants.location')" :placeholder="$t('plants.locationPlaceholder')" />
        <BaseInput v-model="formNotes" :label="$t('plants.notes')" :placeholder="$t('plants.notes')" />
        <label v-if="!formAdvice" class="checkbox-row">
          <input v-model="formAddWaterTask" type="checkbox" />
          <span>{{ $t('plants.addWaterTask') }}</span>
        </label>
        <AiPlantCareCard
          v-if="showAddDialog"
          :plant-name="formSpecies.trim() || formName.trim()"
          :location="formLocation"
          :apply-label="$t('ai.plant.applyToForm')"
          :done="!!formAdvice"
          @apply="adoptAdvice"
        />
        <p v-if="formAdvice" class="form-hint">{{ $t('ai.plant.adoptedForm') }}</p>
      </form>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="closeAddDialog">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            :disabled="!formName.trim() || formSaving"
            @click="handleCreatePlant"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- Delete Confirm Dialog -->
    <BaseDialog :open="!!deletingPlantId" :title="$t('plants.deleteConfirm')" danger @close="deletingPlantId = null">
      <p class="delete-hint">{{ $t('plants.deleteHint') }}</p>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="deletingPlantId = null">
            {{ $t('common.cancel') }}
          </BaseButton>
          <BaseButton variant="danger" @click="handleDelete">
            {{ $t('common.delete') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.section {
  margin-bottom: var(--space-4);
}

.card-title {
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-3) 0;
  color: var(--ink);
}

.water-all-btn {
  width: 100%;
}

/* ── Plant Cards ── */
.plant-card {
  background: var(--card);
  border-radius: var(--radius-card);
  padding: var(--space-4);
  margin-bottom: var(--space-3);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: transform var(--transition-fast);
}

@media (hover: hover) {
  .plant-card:hover {
    transform: scale(1.01);
  }
}

.plant-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.plant-card__title {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.plant-card__name {
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plant-card__details {
  font-size: var(--text-sm);
  color: var(--sub);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plant-card__next {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--sub);
}

.plant-card__next--empty {
  font-style: italic;
}

.plant-card__actions {
  margin-top: var(--space-3);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.plant-card__delete {
  font-size: var(--text-xs);
  color: var(--color-danger);
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
}

.plant-card__delete:hover {
  background: var(--chip);
}

/* ── Due Badges ── */
.due-badge {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-0-5) var(--space-2);
  border-radius: var(--radius-full);
}

.due-badge--overdue {
  background: var(--color-danger);
  color: var(--color-on-danger);
}

.due-badge--today {
  background: var(--color-warning);
  color: var(--color-on-danger);
}

/* ── FAB ── */
.fab {
  position: fixed;
  bottom: calc(80px + env(safe-area-inset-bottom, 0px));
  right: var(--space-4);
  width: 56px;
  height: 56px;
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

.form-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--ink);
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
