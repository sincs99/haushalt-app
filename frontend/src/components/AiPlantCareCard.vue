<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhSparkle } from '@phosphor-icons/vue'
import { useAiStore } from '../stores/ai'
import { adviceKey, planAdvice, planItems } from '../utils/plantCare'
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
/** `selected`: angehakte Plan-Einträge (Schlüssel aus `adviceKey`, PD-P5). */
const emit = defineEmits<{ apply: [advice: AiPlantCareAdvice, selected: string[]] }>()

const aiStore = useAiStore()
const { t } = useI18n()

const advice = computed(() => aiStore.plantAdvice)
const plan = computed(() => (advice.value ? planAdvice(advice.value, props.existingTasks ?? []) : null))

// Vorschau pro Aufgabe „alt → neu“ mit Abwählen (PD-P5). Gemerkt wird, was abgewählt
// wurde — neue Einträge (z. B. nach Nachladen der Aufgaben) sind standardmässig an.
const deselected = ref(new Set<string>())
watch(advice, () => { deselected.value = new Set() })

const items = computed(() => (plan.value ? planItems(plan.value) : []).map(item => {
  const task = t(`plants.careTypes.${item.care_type}`)
  return {
    key: adviceKey(item),
    text: 'id' in item
      ? t('ai.plant.planUpdate', { task, from: item.from, to: item.interval_days })
      : t('ai.plant.planCreate', { task, to: item.interval_days }),
  }
}))
const selectedKeys = computed(() => items.value.map(i => i.key).filter(key => !deselected.value.has(key)))

function toggle(key: string) {
  const next = new Set(deselected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  deselected.value = next
}

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
      <PhSparkle :size="20" />
      {{ t('ai.plant.fetchForPlant') }}
    </BaseButton>
    <p v-if="!plantName.trim()" class="ai-plant__hint">{{ t('ai.plant.needName') }}</p>
    <p v-if="aiStore.plantError" class="ai-plant__error" role="alert">
      {{ t(`errors.${aiStore.plantError}`) }}
    </p>

    <div v-if="advice" class="ai-plant__result">
      <AiPlantAdvice :advice="advice" />
      <fieldset v-if="items.length > 0 && !done" class="ai-plant__plan">
        <legend class="ai-plant__plan-title">{{ t('ai.plant.planTitle') }}</legend>
        <label v-for="item in items" :key="item.key" class="ai-plant__plan-item">
          <input
            type="checkbox"
            :checked="!deselected.has(item.key)"
            :disabled="busy"
            @change="toggle(item.key)"
          />
          <span>{{ item.text }}</span>
        </label>
      </fieldset>
      <BaseButton
        type="button"
        size="sm"
        :loading="busy"
        :disabled="busy || done"
        @click="emit('apply', advice, selectedKeys)"
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

.ai-plant__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ai-plant__plan {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  border: none;
}

.ai-plant__plan-title {
  padding: 0;
  margin-bottom: var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
}

.ai-plant__plan-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 32px;
  font-size: var(--text-sm);
  color: var(--ink);
}

.ai-plant__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
}
</style>
