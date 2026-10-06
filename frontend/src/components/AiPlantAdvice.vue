<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { PhWarning } from '@phosphor-icons/vue'
import type { AiPlantCareAdvice } from '../types'

/** Anzeige eines KI-Pflegevorschlags (Intervalle, Licht, Standort, Giftigkeit). */
defineProps<{ advice: AiPlantCareAdvice }>()
const { t } = useI18n()
</script>

<template>
  <div>
    <h3 class="advice__name">{{ advice.plant_name }}</h3>
    <p v-if="advice.botanical_name" class="advice__botanical">{{ advice.botanical_name }}</p>

    <dl class="advice__facts">
      <dt>{{ t('ai.plant.watering') }}</dt>
      <dd>{{ t('ai.plant.everyDays', { n: advice.watering_interval_days }, advice.watering_interval_days) }}</dd>

      <dt>{{ t('ai.plant.fertilizing') }}</dt>
      <dd>
        {{ advice.fertilizing_interval_days
          ? t('ai.plant.everyDays', { n: advice.fertilizing_interval_days }, advice.fertilizing_interval_days)
          : t('ai.plant.notNeeded') }}
      </dd>

      <dt>{{ t('ai.plant.repotting') }}</dt>
      <dd>
        {{ advice.repotting_interval_months
          ? t('ai.plant.everyMonths', { n: advice.repotting_interval_months }, advice.repotting_interval_months)
          : t('ai.plant.rarely') }}
      </dd>

      <dt>{{ t('ai.plant.light') }}</dt>
      <dd>{{ t(`ai.plant.lightValues.${advice.light}`) }}</dd>
    </dl>

    <h4 class="advice__title">{{ t('ai.plant.location') }}</h4>
    <p class="advice__text">{{ advice.location_tip }}</p>

    <h4 class="advice__title">{{ t('ai.plant.care') }}</h4>
    <p class="advice__text">{{ advice.care_notes }}</p>

    <div class="advice__pets" :class="`advice__pets--${advice.pet_toxicity}`">
      <PhWarning v-if="advice.pet_toxicity === 'toxic'" :size="18" />
      <div>
        <strong>{{ t('ai.plant.petToxicity') }}: {{ t(`ai.plant.toxicity.${advice.pet_toxicity}`) }}</strong>
        <p v-if="advice.pet_toxicity_note" class="advice__text">{{ advice.pet_toxicity_note }}</p>
        <p class="advice__vet">{{ t('ai.plant.vetDisclaimer') }}</p>
      </div>
    </div>

    <p class="advice__disclaimer">{{ t('ai.disclaimer') }}</p>
  </div>
</template>

<style scoped>
.advice__name {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  color: var(--ink);
}

.advice__botanical {
  margin: 0;
  font-style: italic;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.advice__facts {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-3);
  margin: var(--space-3) 0 0;
  font-size: var(--text-sm);
}

.advice__facts dt {
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.advice__facts dd {
  margin: 0;
  color: var(--ink);
}

.advice__title {
  margin: var(--space-3) 0 var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.advice__text {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--line-height-normal);
  color: var(--ink);
}

.advice__pets {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-btn);
  background: var(--chip);
  font-size: var(--text-sm);
  color: var(--ink);
}

.advice__pets--toxic {
  background: var(--color-danger-light);
}

.advice__vet,
.advice__disclaimer {
  margin: var(--space-1) 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.advice__disclaimer {
  margin-top: var(--space-3);
}
</style>
