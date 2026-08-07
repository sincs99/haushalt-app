<script setup lang="ts">
import { PhCheck } from '@phosphor-icons/vue'

defineProps<{
  checked: boolean
}>()

defineEmits<{
  toggle: []
}>()
</script>

<template>
  <button
    type="button"
    class="check-circle"
    :class="{ 'check-circle--checked': checked }"
    @click.stop="$emit('toggle')"
    :aria-checked="checked"
    role="checkbox"
  >
    <PhCheck v-if="checked" :size="12" weight="bold" class="check-circle__icon" />
  </button>
</template>

<style scoped>
.check-circle {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-full);
  border: 2px solid var(--line-strong);
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  transition: all 150ms ease;
}

.check-circle--checked {
  background: var(--ok);
  border-color: var(--ok);
}

.check-circle__icon {
  color: #fff;
}
</style>
