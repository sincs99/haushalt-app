<script setup lang="ts">
/**
 * Medikament anlegen (`medication` = null) oder bearbeiten. Das Formular wird beim
 * Öffnen aus `medication` befüllt; nach erfolgreichem Speichern schliesst der Dialog.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePetsStore, type Clearable } from '../../stores/pets'
import { useAsyncAction } from '../../composables/useAsyncAction'
import type { Medication, MedicationCreatePayload, MedicationUpdatePayload } from '../../types'
import BaseButton from '../ui/BaseButton.vue'
import BaseDialog from '../ui/BaseDialog.vue'
import BaseInput from '../ui/BaseInput.vue'

const props = defineProps<{
  modelValue: boolean
  petId: string
  /** Zu bearbeitendes Medikament; null = neues anlegen */
  medication: Medication | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const petsStore = usePetsStore()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const editingMedId = ref<string | null>(null)
const medFormName = ref('')
const medFormDosage = ref('')
const medFormSchedule = ref('')
const medFormActive = ref(true)
const medSaving = computed(() => isPending('med-save'))

// Beim Öffnen befüllen: leer (neu) bzw. mit den Werten des Medikaments
watch(() => props.modelValue, (open) => {
  if (!open) return
  const med = props.medication
  editingMedId.value = med?.id ?? null
  medFormName.value = med?.name ?? ''
  medFormDosage.value = med?.dosage ?? ''
  medFormSchedule.value = med?.schedule ?? ''
  medFormActive.value = med ? med.active : true
})

function closeMedDialog() {
  emit('update:modelValue', false)
}

async function handleSaveMedication() {
  const name = medFormName.value.trim()
  if (!name) return

  const editingId = editingMedId.value
  const ok = await run(async () => {
    if (editingId) {
      // Geleerte Felder als null senden, sonst bleibt der alte Wert gespeichert
      const payload: Clearable<MedicationUpdatePayload> = {
        name,
        dosage: medFormDosage.value.trim() || null,
        schedule: medFormSchedule.value.trim() || null,
        active: medFormActive.value,
      }
      await petsStore.updateMedication(props.petId, editingId, payload)
    } else {
      const payload: MedicationCreatePayload = {
        name,
        dosage: medFormDosage.value.trim() || undefined,
        schedule: medFormSchedule.value.trim() || undefined,
        active: medFormActive.value,
      }
      const created = await petsStore.createMedication(props.petId, payload)
      if (created) {
        await petsStore.fetchMedicationLog(props.petId, created.id)
      }
    }
  }, {
    key: 'med-save',
    success: editingId ? t('pets.medicationUpdated') : t('pets.medicationCreated'),
    error: t('pets.medicationSaveError'),
  })
  if (ok) emit('update:modelValue', false)
}
</script>

<template>
  <!-- ═══ Add / Edit Medication Dialog ═══ -->
  <BaseDialog
    :open="modelValue"
    :title="editingMedId ? $t('pets.editMedication') : $t('pets.addMedication')"
    @close="closeMedDialog"
  >
    <form id="pet-med-form" class="dialog-form" @submit.prevent="handleSaveMedication">
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
          type="submit"
          form="pet-med-form"
          :disabled="!medFormName.trim() || medSaving"
          :loading="medSaving"
        >
          {{ $t('common.save') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>

<style scoped>
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
  min-height: var(--touch-target); /* ganze Zeile ist Tap-Ziel der Checkbox */
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
</style>
