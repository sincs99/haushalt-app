<script setup lang="ts">
import type { Component } from 'vue'
import { Package } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  icon?: Component
  title: string
  subtitle?: string
}>(), {})
</script>

<template>
  <div class="base-empty-state">
    <component :is="icon ?? Package" :size="48" class="base-empty-state__icon" aria-hidden="true" />
    <p class="base-empty-state__title">{{ title }}</p>
    <p v-if="subtitle" class="base-empty-state__subtitle">{{ subtitle }}</p>
    <div v-if="$slots.action" class="empty-state__action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.base-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-8) var(--space-4);
}

.base-empty-state__icon {
  color: var(--color-text-muted);
  margin-bottom: var(--space-3);
}

.base-empty-state__title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.base-empty-state__subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
}

.empty-state__action {
  margin-top: var(--space-4);
}
</style>
