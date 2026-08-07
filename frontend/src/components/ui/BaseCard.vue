<script setup lang="ts">
withDefaults(defineProps<{
  padding?: 'sm' | 'md' | 'lg'
}>(), {
  padding: 'md',
})
</script>

<template>
  <div class="base-card" :class="`base-card--${padding}`">
    <slot />
  </div>
</template>

<style scoped>
.base-card {
  background: var(--card);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
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
