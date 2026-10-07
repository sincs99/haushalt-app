<script setup lang="ts">
withDefaults(defineProps<{
  padding?: 'sm' | 'md' | 'lg'
}>(), {
  padding: 'md',
})
</script>

<template>
  <div class="base-card" :class="`base-card--${padding}`">
    <header v-if="$slots.header" class="base-card__header">
      <slot name="header" />
    </header>
    <slot />
  </div>
</template>

<style scoped>
.base-card {
  background: var(--card);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.base-card__header {
  margin-bottom: var(--space-3);
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.base-card--sm {
  padding: var(--space-3);
}

.base-card--md {
  padding: var(--space-4);
}

.base-card--lg {
  padding: var(--space-6);
}
</style>
