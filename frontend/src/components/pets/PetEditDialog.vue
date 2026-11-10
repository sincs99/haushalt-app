<script setup lang="ts">
/**
 * Tier bearbeiten (Steckbrief + Gesundheitseinträge). Das Formular wird beim Öffnen
 * aus `pet` befüllt; nach erfolgreichem Speichern schliesst der Dialog.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePetsStore, type Clearable } from '../../stores/pets'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { parseWeightKgToGrams } from '../../utils/money'
import type { Pet, PetUpdatePayload, HealthEntry } from '../../types'
import { PhPlus, PhTrash } from '@phosphor-icons/vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseDialog from '../ui/BaseDialog.vue'
import BaseInput from '../ui/BaseInput.vue'

const props = defineProps<{
  modelValue: boolean
  pet: Pet
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const petsStore = usePetsStore()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

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
const editPetSaving = computed(() => isPending('pet-save'))
// Inline-Fehler am Gewichtsfeld
const editFormWeightError = ref('')

watch(editFormWeightGrams, () => { editFormWeightError.value = '' })

// Beim Öffnen mit den aktuellen Werten des Tiers befüllen
watch(() => props.modelValue, (open) => {
  if (!open) return
  const pet = props.pet
  editFormName.value = pet.name
  editFormBreed.value = pet.breed ?? ''
  editFormBirthdate.value = pet.birthdate ?? ''
  editFormWeightGrams.value = pet.weight_grams
    ? (pet.weight_grams / 1000).toFixed(1).replace('.', ',')
    : ''
  editFormNotes.value = pet.notes ?? ''
  editFormChipNumber.value = pet.chip_number ?? ''
  editFormInsurance.value = pet.insurance ?? ''
  editFormVetName.value = pet.vet_name ?? ''
  editFormFoodNotes.value = pet.food_notes ?? ''
  editFormHealthEntries.value = pet.health_entries
    ? pet.health_entries.map(e => ({ ...e }))
    : []
  editFormWeightError.value = ''
})

function closeEditPetDialog() {
  emit('update:modelValue', false)
}

function addHealthEntry() {
  editFormHealthEntries.value.push({ title: '', subtitle: '', severity: 'green' })
}

function removeHealthEntry(index: number) {
  editFormHealthEntries.value.splice(index, 1)
}

async function handleUpdatePet() {
  const name = editFormName.value.trim()
  if (!name) return

  const weightResult = parseWeightKgToGrams(editFormWeightGrams.value)
  if (weightResult === null) {
    editFormWeightError.value = t('pets.invalidWeight')
    return
  }

  // Filter out empty health entries
  const validEntries = editFormHealthEntries.value.filter(e => e.title.trim())

  // Geleerte Felder als null senden (bzw. [] für Gesundheit), sonst bleibt der alte Wert
  const payload: Clearable<PetUpdatePayload> = {
    name,
    breed: editFormBreed.value.trim() || null,
    birthdate: editFormBirthdate.value || null,
    weight_grams: weightResult ?? null,
    notes: editFormNotes.value.trim() || null,
    chip_number: editFormChipNumber.value.trim() || null,
    insurance: editFormInsurance.value.trim() || null,
    vet_name: editFormVetName.value.trim() || null,
    food_notes: editFormFoodNotes.value.trim() || null,
    health_entries: validEntries,
  }
  const ok = await run(() => petsStore.updatePet(props.pet.id, payload), {
    key: 'pet-save',
    success: t('pets.updated'),
    error: t('pets.updateError'),
  })
  if (ok) emit('update:modelValue', false)
}
</script>

<template>
  <!-- ═══ Edit Pet Dialog ═══ -->
  <BaseDialog
    :open="modelValue"
    :title="$t('pets.editPet')"
    @close="closeEditPetDialog"
  >
    <form id="pet-edit-form" class="dialog-form" @submit.prevent="handleUpdatePet">
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
        :placeholder="$t('pets.weightPlaceholder')"
        :error="editFormWeightError || undefined"
        type="text"
        inputmode="decimal"
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
            class="health-editor__delete tap-target"
            @click="removeHealthEntry(i)"
            :aria-label="$t('common.delete')"
          >
            <PhTrash :size="16" />
          </button>
        </div>
        <button
          type="button"
          class="health-editor__add tap-target"
          @click="addHealthEntry"
        >
          <PhPlus :size="16" weight="bold" />
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
          type="submit"
          form="pet-edit-form"
          :disabled="!editFormName.trim() || editPetSaving"
          :loading="editPetSaving"
        >
          {{ $t('common.save') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>

<style scoped>
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
  /* Abstand, damit die Tap-Fläche von „Löschen“ nicht über dem Eingabefeld liegt */
  gap: var(--space-3);
  padding: var(--space-2);
  background: var(--chip);
  border-radius: var(--radius-sm);
}

.health-editor__severity {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding-top: var(--space-1);
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
.severity-btn--yellow { background: var(--color-warning); }
.severity-btn--red { background: var(--color-danger); }

.health-editor__fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.health-editor__input {
  width: 100%;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  color: var(--ink);
  background: var(--card);
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
  color: var(--color-danger);
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
</style>
