<script setup lang="ts">
import BaseSpinner from './BaseSpinner.vue'

withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'md' | 'sm'
  disabled?: boolean
  loading?: boolean
  type?: 'button' | 'submit'
}>(), {
  variant: 'primary',
  size: 'md',
  disabled: false,
  loading: false,
  type: 'button',
})
</script>

<template>
  <button
    class="base-btn"
    :class="[
      `base-btn--${variant}`,
      `base-btn--${size}`,
      { 'base-btn--loading': loading },
    ]"
    :type="type"
    :disabled="disabled || loading"
  >
    <BaseSpinner v-if="loading" :size="size === 'sm' ? 'sm' : 'md'" class="base-btn__spinner" />
    <span v-else class="base-btn__content">
      <slot />
    </span>
  </button>
</template>

<style scoped>
.base-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background-color var(--transition-fast),
              color var(--transition-fast),
              border-color var(--transition-fast);
  white-space: nowrap;
  user-select: none;
  line-height: var(--line-height-tight);
}

/* --- Sizes --- */
.base-btn--md {
  min-height: 44px;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-base);
}

.base-btn--sm {
  min-height: 36px;
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
}

/* --- Variants --- */
.base-btn--primary {
  background-color: var(--color-primary);
  color: var(--color-surface);
}
.base-btn--primary:hover:not(:disabled) {
  background-color: var(--color-primary-hover);
}

.base-btn--primary:active:not(:disabled) {
  background-color: var(--color-primary-dark);
  transform: scale(0.98);
}

.base-btn--secondary {
  background-color: var(--color-surface);
  color: var(--color-text);
  border-color: var(--color-neutral-300);
}
.base-btn--secondary:hover:not(:disabled) {
  background-color: var(--color-neutral-100);
}

.base-btn--secondary:active:not(:disabled) {
  background-color: var(--color-neutral-200);
  transform: scale(0.98);
}

.base-btn--danger {
  background-color: var(--color-danger);
  color: var(--color-surface);
}
.base-btn--danger:hover:not(:disabled) {
  background-color: var(--color-danger-hover);
}

.base-btn--danger:active:not(:disabled) {
  background-color: var(--color-danger-hover);
  transform: scale(0.98);
}

.base-btn--ghost {
  background-color: transparent;
  color: var(--color-primary);
}
.base-btn--ghost:hover:not(:disabled) {
  background-color: var(--color-primary-light);
}

.base-btn--ghost:active:not(:disabled) {
  background-color: var(--color-neutral-200);
  transform: scale(0.98);
}

/* --- Disabled --- */
.base-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* --- Focus visible --- */
.base-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* --- Loading --- */
.base-btn--loading {
  cursor: wait;
}

.base-btn__content {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
