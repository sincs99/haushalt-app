<script setup lang="ts">
withDefaults(defineProps<{
  icon?: string
  title: string
  subtitle?: string
}>(), {
  icon: '📭',
})
</script>

<template>
  <div class="base-empty-state">
    <span class="base-empty-state__icon" aria-hidden="true">{{ icon }}</span>
    <p class="base-empty-state__title">{{ title }}</p>
    <p v-if="subtitle" class="base-empty-state__subtitle">{{ subtitle }}</p>
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
  font-size: 48px;
  line-height: 1;
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
</style>
