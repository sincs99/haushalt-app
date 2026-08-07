<script setup lang="ts">
import { watch, nextTick, ref } from 'vue'
import { PhX } from '@phosphor-icons/vue'

const props = withDefaults(defineProps<{
  open: boolean
  title?: string
  danger?: boolean
}>(), {
  danger: false,
})

const emit = defineEmits<{
  close: []
}>()

const dialogRef = ref<HTMLElement | null>(null)

watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    dialogRef.value?.focus()
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="open" class="dialog-overlay" @click.self="emit('close')" @keydown="onKeydown">
        <div
          ref="dialogRef"
          class="dialog-panel"
          role="dialog"
          aria-modal="true"
          tabindex="-1"
        >
          <div class="dialog-header" v-if="title">
            <h2 class="dialog-title">{{ title }}</h2>
            <button class="dialog-close" @click="emit('close')" :aria-label="$t('common.close')">
              <PhX :size="18" />
            </button>
          </div>
          <div class="dialog-body">
            <slot />
          </div>
          <div class="dialog-footer" v-if="$slots.footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(2px);
}

.dialog-panel {
  background: var(--card);
  border-radius: var(--radius-dialog);
  box-shadow: var(--shadow-overlay);
  width: 100%;
  max-width: 420px;
  max-height: 90vh;
  overflow-y: auto;
  outline: none;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--line);
}

.dialog-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.dialog-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
}

.dialog-close:hover {
  color: var(--ink);
  background: var(--chip);
}

.dialog-body {
  padding: var(--space-4) var(--space-6);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-6);
  border-top: 1px solid var(--line);
}

/* Transitions */
.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.15s ease;
}
.dialog-enter-active .dialog-panel,
.dialog-leave-active .dialog-panel {
  transition: transform 0.15s ease;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
.dialog-enter-from .dialog-panel,
.dialog-leave-to .dialog-panel {
  transform: scale(0.95);
}
</style>
