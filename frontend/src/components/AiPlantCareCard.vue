<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhSparkle } from '@phosphor-icons/vue'
import { useAiStore } from '../stores/ai'
import { planAdvice } from '../utils/plantCare'
import type { AiPlantCareAdvice, PlantCareTask } from '../types'
import AiPlantAdvice from './AiPlantAdvice.vue'
import BaseButton from './ui/BaseButton.vue'

/**
 * KI-Pflegehinweise im Pflanzen-Modul: holt den Vorschlag, zeigt ihn an und meldet
 * per `apply`, wenn die Person ihn übernehmen will. Gespeichert wird hier nichts —
 * das macht der Aufrufer (Formular beim Speichern, Detailansicht sofort).
 * Sichtbar nur, wenn Server-Schlüssel UND Haushalts-Opt-in vorhanden sind.
 */
const props = defineProps<{
  /** Pflanzenname bzw. Art aus dem Formular */
  plantName: string
  location?: string
  applyLabel: string
  /** Bestehende Aufgaben: für die Vorschau "neu / anpassen" */
  existingTasks?: PlantCareTask[]
  busy?: boolean
  done?: boolean
}>()
const emit = defineEmits<{ apply: [advice: AiPlantCareAdvice] }>()

const aiStore = useAiStore()
const { t } = useI18n()

const advice = computed(() => aiStore.plantAdvice)
const plan = computed(() => (advice.value ? planAdvice(advice.value, props.existingTasks ?? []) : null))

onMounted(() => {
  aiStore.fetchStatus()
  // Das Ergebnis ist geteilter Store-State (auch vom Assistenten genutzt) → sauber starten
  aiStore.clearPlant()
})
onUnmounted(() => aiStore.clearPlant())

async function fetchAdvice() {
  await aiStore.fetchPlantCare(props.plantName, props.location)
}
</script>

<template>
  <div v-if="aiStore.enabledForHousehold" class="ai-plant">
    <BaseButton
      variant="secondary"
      size="sm"
      type="button"
      :loading="aiStore.plantLoading"
      :disabled="!plantName.trim() || aiStore.plantLoading"
      @click="fetchAdvice"
    >
      <PhSparkle :size="18" />
      {{ t('ai.plant.fetchForPlant') }}
    </BaseButton>
    <p v-if="!plantName.trim()" class="ai-plant__hint">{{ t('ai.plant.needName') }}</p>
    <p v-if="aiStore.plantError" class="ai-plant__error" role="alert">
      {{ t(`errors.${aiStore.plantError}`) }}
    </p>

    <div v-if="advice" class="ai-plant__result">
      <AiPlantAdvice :advice="advice" />
      <p v-if="plan && (plan.create.length || plan.update.length)" class="ai-plant__plan">
        {{ t('ai.plant.applyPlan', { create: plan.create.length, update: plan.update.length }) }}
      </p>
      <BaseButton
        type="button"
        size="sm"
        :loading="busy"
        :disabled="busy || done"
        @click="emit('apply', advice)"
      >
        {{ done ? t('ai.plant.adopted') : applyLabel }}
      </BaseButton>
      <p v-if="!done" class="ai-plant__hint">{{ t('ai.plant.nothingSavedYet') }}</p>
    </div>
  </div>
</template>

<style scoped>
.ai-plant {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.ai-plant__result {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3);
  border-radius: var(--radius-btn);
  background: var(--chip);
}

.ai-plant__hint,
.ai-plant__plan {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ai-plant__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
}
</style>
