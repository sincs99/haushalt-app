<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhPlant } from '@phosphor-icons/vue'
import { useAiStore } from '../stores/ai'
import { useAuthStore } from '../stores/auth'
import AiPlantAdvice from '../components/AiPlantAdvice.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import PageHeader from '../components/ui/PageHeader.vue'

/**
 * KI-Assistent: Pflanzenpflege-Hinweise. Dieselben Hinweise holt das
 * Pflanzen-Modul über AiPlantCareCard zur Vorbefüllung der Pflegeaufgaben.
 */
const aiStore = useAiStore()
const authStore = useAuthStore()
const { t, te } = useI18n()

const isAdmin = computed(() => authStore.currentHousehold?.role === 'admin')
const retrying = ref(false)

/** Fehlercode → Text; unbekannte Codes nicht als rohen Schlüssel zeigen. */
const plantErrorText = computed(() => {
  const code = aiStore.plantError
  if (!code) return ''
  return te(`errors.${code}`) ? t(`errors.${code}`) : t('errors.unknown')
})

async function retryStatus() {
  retrying.value = true
  try {
    await aiStore.fetchStatus(true)
  } finally {
    retrying.value = false
  }
}

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

    <!-- Status konnte nicht geladen werden (offline/Netzfehler) – nicht „nicht eingerichtet“ -->
    <BaseCard v-if="aiStore.available === null && aiStore.statusError">
      <BaseErrorState :retrying="retrying" @retry="retryStatus" />
    </BaseCard>

    <!-- Status wird geladen -->
    <BaseCard v-else-if="aiStore.available === null">
      <BaseSkeleton height="20px" />
      <BaseSkeleton height="20px" width="60%" style="margin-top: var(--space-2)" />
    </BaseCard>

    <BaseCard v-else-if="aiStore.available === false">
      <p class="assistant-hint">{{ t('ai.notAvailable') }}</p>
    </BaseCard>

    <BaseCard v-else-if="aiStore.available && !aiStore.enabledForHousehold">
      <p class="assistant-hint">{{ t('ai.notEnabled') }}</p>
      <RouterLink v-if="isAdmin" to="/household" class="assistant-link">{{ t('nav.settings') }}</RouterLink>
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
            {{ plantErrorText }}
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
        <AiPlantAdvice :advice="advice" />
      </BaseCard>
    </template>
  </div>
</template>

<style scoped>
.assistant-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
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
</style>
