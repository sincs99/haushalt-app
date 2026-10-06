<script setup lang="ts">
withDefaults(defineProps<{
  size?: 'sm' | 'md'
}>(), {
  size: 'md',
})
</script>

<template>
  <span
    class="base-spinner"
    :class="`base-spinner--${size}`"
    role="status"
    aria-label="Lädt…"
  />
</template>

<style scoped>
.base-spinner {
  display: inline-block;
  border-radius: var(--radius-full);
  border-style: solid;
  border-color: var(--line-strong);
  border-top-color: var(--acc);
  animation: spin 0.6s linear infinite;
}

.base-spinner--sm {
  width: var(--icon-size-sm);
  height: var(--icon-size-sm);
  border-width: 2px;
}

.base-spinner--md {
  width: var(--icon-size-lg);
  height: var(--icon-size-lg);
  border-width: 3px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
