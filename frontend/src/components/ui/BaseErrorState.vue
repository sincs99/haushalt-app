<script setup lang="ts">
import { PhWarningCircle, PhArrowClockwise } from '@phosphor-icons/vue'
import BaseButton from './BaseButton.vue'

/**
 * Fehlerzustand für Listen: Meldung + „Erneut versuchen“.
 * Gegenstück zu BaseEmptyState, wenn das Laden gescheitert ist.
 */
withDefaults(defineProps<{
  message?: string
  retrying?: boolean
}>(), {
  retrying: false,
})

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="base-error-state" role="alert">
    <PhWarningCircle :size="40" class="base-error-state__icon" aria-hidden="true" />
    <p class="base-error-state__text">{{ message ?? $t('common.loadError') }}</p>
    <BaseButton variant="secondary" size="sm" :loading="retrying" @click="emit('retry')">
      <PhArrowClockwise :size="16" aria-hidden="true" />
      {{ $t('common.retry') }}
    </BaseButton>
  </div>
</template>

<style scoped>
.base-error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  text-align: center;
  padding: var(--space-8) var(--space-4);
}

.base-error-state__icon {
  color: var(--color-danger);
}

.base-error-state__text {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
  line-height: var(--line-height-normal);
  max-width: 32ch;
}
</style>
