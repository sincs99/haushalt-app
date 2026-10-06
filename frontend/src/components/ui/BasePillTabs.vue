<script setup lang="ts">
defineProps<{
  tabs: Array<{ key: string; label: string }>
  modelValue: string
}>()

defineEmits<{
  'update:modelValue': [key: string]
}>()
</script>

<template>
  <div class="pill-tabs">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      class="pill-tab"
      :class="{ 'pill-tab--active': modelValue === tab.key }"
      @click="$emit('update:modelValue', tab.key)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

<style scoped>
.pill-tabs {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.pill-tab {
  padding: var(--chip-padding);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
  border: none;
  font-family: var(--font-family);
  background: var(--chip);
  color: var(--ink);
}

.pill-tab:hover:not(.pill-tab--active) {
  filter: brightness(0.96);
}

.pill-tab:active {
  transform: scale(0.97);
}

.pill-tab:focus-visible {
  outline: var(--focus-outline);
  outline-offset: 2px;
}

.pill-tab--active {
  background: var(--ink);
  color: var(--card);
}
</style>
