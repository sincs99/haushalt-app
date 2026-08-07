<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { PhWallet, PhCat, PhForkKnife, PhNote, PhGear } from '@phosphor-icons/vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const router = useRouter()
const { t } = useI18n()

function navigate(path: string) {
  router.push(path)
  emit('close')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) {
    emit('close')
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})

// Body-Scroll sperren wenn Sheet offen
watch(() => props.open, (isOpen) => {
  document.body.style.overflow = isOpen ? 'hidden' : ''
})

const entries = [
  { label: 'nav.expenses', icon: PhWallet, action: () => navigate('/expenses'), disabled: false },
  { label: 'nav.cats', icon: PhCat, action: undefined, disabled: true },
  { label: 'nav.meals', icon: PhForkKnife, action: undefined, disabled: true },
  { label: 'nav.notes', icon: PhNote, action: undefined, disabled: true },
  { label: 'nav.settings', icon: PhGear, action: () => navigate('/household'), disabled: false },
]
</script>

<template>
  <Teleport to="body">
    <Transition name="backdrop">
      <div
        v-if="open"
        class="more-sheet-backdrop"
        @click.self="emit('close')"
      >
        <Transition name="sheet" appear>
          <div class="more-sheet" role="dialog" aria-modal="true" :aria-label="t('moreSheet.title')">
            <div class="more-sheet__handle" />
            <ul class="more-sheet__list">
              <li
                v-for="entry in entries"
                :key="entry.label"
                class="more-sheet__item"
                :class="{ 'more-sheet__item--disabled': entry.disabled }"
                @click="entry.action?.()"
              >
                <component :is="entry.icon" :size="20" class="more-sheet__icon" />
                <span class="more-sheet__label">{{ t(entry.label) }}</span>
                <span v-if="entry.disabled" class="more-sheet__badge">
                  {{ t('moreSheet.comingSoon') }}
                </span>
              </li>
            </ul>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.more-sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
}

.more-sheet {
  width: 100%;
  background: var(--card);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  padding: var(--space-3) var(--space-4) calc(var(--space-4) + env(safe-area-inset-bottom, 0));
  box-shadow: var(--shadow-overlay);
}

.more-sheet__handle {
  width: 36px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--line-strong);
  margin: 0 auto var(--space-4);
}

.more-sheet__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.more-sheet__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition-fast);
  color: var(--ink);
}

.more-sheet__item:hover:not(.more-sheet__item--disabled) {
  background: var(--chip);
}

.more-sheet__item--disabled {
  opacity: 0.4;
  pointer-events: none;
  cursor: default;
}

.more-sheet__icon {
  flex-shrink: 0;
  color: var(--sub);
}

.more-sheet__label {
  flex: 1;
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
}

.more-sheet__badge {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  background: var(--acc-soft);
  color: var(--acc);
}

/* --- Backdrop Transition --- */
.backdrop-enter-active,
.backdrop-leave-active {
  transition: opacity 0.2s ease;
}

.backdrop-enter-from,
.backdrop-leave-to {
  opacity: 0;
}

/* --- Sheet Slide-Up Transition --- */
.sheet-enter-active {
  transition: transform 0.25s ease-out;
}

.sheet-leave-active {
  transition: transform 0.2s ease-in;
}

.sheet-enter-from,
.sheet-leave-to {
  transform: translateY(100%);
}
</style>
