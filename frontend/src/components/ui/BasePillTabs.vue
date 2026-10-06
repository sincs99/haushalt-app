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
      class="pill-tab tap-target"
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
  /* Raum für die vergrösserte Tap-Fläche, die der Scroll-Container sonst abschneidet */
  padding-block: var(--space-2);
  margin-block: calc(-1 * var(--space-2));
  -webkit-overflow-scrolling: touch;
}

.pill-tab {
  padding: 6px 16px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  border: none;
  font-family: var(--font-family);
  background: var(--chip);
  color: var(--ink);
}

.pill-tab--active {
  background: var(--ink);
  color: var(--card);
}
</style>
