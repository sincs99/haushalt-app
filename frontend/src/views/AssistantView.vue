<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhPlant, PhWarning } from '@phosphor-icons/vue'
import { useAiStore } from '../stores/ai'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import PageHeader from '../components/ui/PageHeader.vue'

/**
 * KI-Assistent: vorerst Pflanzenpflege-Hinweise. Das Pflanzen-Modul bindet
 * denselben Endpunkt später zur Vorbefüllung der Pflegeaufgaben ein.
 */
const aiStore = useAiStore()
const { t } = useI18n()

const plant = ref('')
const location = ref('')

const advice = computed(() => aiStore.plantAdvice)

onMounted(() => {
  aiStore.fetchStatus()
})

async function ask() {
  await aiStore.fetchPlantCare(plant.value, location.value)
}
</script>

<template>
  <div class="assistant-view">
    <PageHeader :title="t('ai.title')" />

    <BaseCard v-if="aiStore.available === false">
      <p class="assistant-hint">{{ t('ai.notAvailable') }}</p>
    </BaseCard>

    <BaseCard v-else-if="aiStore.available && !aiStore.enabledForHousehold">
      <p class="assistant-hint">{{ t('ai.notEnabled') }}</p>
      <RouterLink to="/household" class="assistant-link">{{ t('nav.settings') }}</RouterLink>
    </BaseCard>

    <template v-else-if="aiStore.enabledForHousehold">
      <BaseCard>
        <h3 class="assistant-card__header">
          <PhPlant :size="20" />
          <span>{{ t('ai.plant.title') }}</span>
        </h3>

        <form class="assistant-form" @submit.prevent="ask">
          <BaseInput
            v-model="plant"
            :label="t('ai.plant.plantLabel')"
            :placeholder="t('ai.plant.plantPlaceholder')"
            maxlength="100"
          />
          <BaseInput
            v-model="location"
            :label="t('ai.plant.locationLabel')"
            :placeholder="t('ai.plant.locationPlaceholder')"
            maxlength="200"
          />
          <p v-if="aiStore.plantError" class="assistant-error" role="alert">
            {{ t(`errors.${aiStore.plantError}`) }}
          </p>
          <BaseButton
            type="submit"
            :loading="aiStore.plantLoading"
            :disabled="!plant.trim() || aiStore.plantLoading"
          >
            {{ t('ai.plant.ask') }}
          </BaseButton>
        </form>
      </BaseCard>

      <BaseCard v-if="advice">
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
      </BaseCard>
    </template>
  </div>
</template>

<style scoped>
.assistant-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4);
  padding-bottom: calc(var(--space-6) + 80px); /* Platz für Bottom-Nav */
  max-width: 600px;
  margin: 0 auto;
}

.assistant-hint {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.assistant-link {
  display: inline-block;
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}

.assistant-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  font-size: var(--text-base);
  font-family: var(--font-display);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.assistant-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.assistant-error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
}

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
  line-height: 1.5;
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
