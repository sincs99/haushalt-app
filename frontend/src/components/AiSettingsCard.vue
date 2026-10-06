<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhSparkle } from '@phosphor-icons/vue'
import { useAiStore } from '../stores/ai'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import { translateApiError } from '../utils/apiErrors'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'

/**
 * Haushaltseinstellungen → KI-Assistent.
 * Nur sichtbar, wenn der Server einen Schlüssel hat; nur Admins schalten um.
 */
const aiStore = useAiStore()
const authStore = useAuthStore()
const { t } = useI18n()
const { showToast } = useToast()

const busy = ref(false)
const isAdmin = computed(() => authStore.currentHousehold?.role === 'admin')
const enabled = computed(() => authStore.currentHousehold?.ai_enabled === true)

async function load() {
  await aiStore.fetchStatus()
  if (aiStore.available) {
    try {
      await aiStore.fetchSettings()
    } catch {
      // Einstellungen sind optional für die Anzeige
    }
  }
}

async function toggle() {
  if (busy.value) return
  busy.value = true
  try {
    await aiStore.setEnabled(!enabled.value)
  } catch (error) {
    showToast(translateApiError(error), 'error')
  } finally {
    busy.value = false
  }
}

onMounted(load)
watch(() => authStore.currentHouseholdId, load)
</script>

<template>
  <BaseCard v-if="aiStore.available">
    <h2 class="ai-settings__title">
      <PhSparkle :size="20" />
      {{ t('ai.title') }}
    </h2>

    <div class="ai-settings__row">
      <span class="ai-settings__state">
        {{ enabled ? t('ai.settings.enabledState') : t('ai.settings.disabledState') }}
      </span>
      <BaseButton
        v-if="isAdmin"
        :variant="enabled ? 'secondary' : 'primary'"
        size="sm"
        :loading="busy"
        @click="toggle"
      >
        {{ enabled ? t('ai.settings.disable') : t('ai.settings.enable') }}
      </BaseButton>
    </div>

    <p class="ai-settings__hint">{{ t('ai.settings.privacyHint') }}</p>
    <p v-if="!isAdmin" class="ai-settings__hint">{{ t('ai.settings.adminOnly') }}</p>
    <p v-if="enabled && aiStore.settings" class="ai-settings__hint">
      {{ t('ai.settings.usage', { used: aiStore.settings.calls_today, limit: aiStore.settings.daily_limit }) }}
    </p>

    <RouterLink v-if="enabled" to="/assistant" class="ai-settings__link">
      {{ t('ai.settings.openAssistant') }}
    </RouterLink>
  </BaseCard>
</template>

<style scoped>
.ai-settings__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.ai-settings__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.ai-settings__state {
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
}

.ai-settings__hint {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.ai-settings__link {
  display: inline-block;
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}
</style>
