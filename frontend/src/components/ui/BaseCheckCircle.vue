<script setup lang="ts">
import { PhCheck } from '@phosphor-icons/vue'

defineProps<{
  checked: boolean
  /** Zugänglicher Name, z. B. der Titel des Eintrags */
  label?: string
}>()

defineEmits<{
  toggle: []
}>()
</script>

<template>
  <button
    type="button"
    class="check-circle tap-target"
    :class="{ 'check-circle--checked': checked }"
    @click.stop="$emit('toggle')"
    :aria-checked="checked"
    :aria-label="label"
    role="checkbox"
  >
    <PhCheck v-if="checked" :size="12" weight="bold" class="check-circle__icon" />
  </button>
</template>

<style scoped>
.check-circle {
  width: var(--check-size);
  height: var(--check-size);
  border-radius: var(--radius-full);
  border: 2px solid var(--line-strong);
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  transition: background-color var(--transition-fast),
              border-color var(--transition-fast),
              transform var(--transition-fast);
}

.check-circle:hover {
  border-color: var(--ok);
}

.check-circle:active {
  transform: scale(0.92);
}

.check-circle:focus-visible {
  outline: var(--focus-outline);
  outline-offset: 2px;
}

.check-circle--checked {
  background: var(--ok);
  border-color: var(--ok);
}

.check-circle__icon {
  color: var(--color-on-success);
}
</style>
