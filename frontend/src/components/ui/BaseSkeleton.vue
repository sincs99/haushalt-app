<script setup lang="ts">
withDefaults(defineProps<{
  width?: string
  height?: string
  rounded?: boolean
}>(), {
  width: '100%',
  height: '16px',
  rounded: false,
})
</script>

<template>
  <div
    class="base-skeleton"
    :class="{ 'base-skeleton--rounded': rounded }"
    :style="{ width, height }"
    aria-hidden="true"
  />
</template>

<style scoped>
.base-skeleton {
  background: var(--chip);
  border-radius: var(--radius-sm);
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.base-skeleton--rounded {
  border-radius: var(--radius-full);
}

@keyframes skeleton-pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}
</style>
