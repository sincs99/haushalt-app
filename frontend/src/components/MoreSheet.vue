<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { PhWallet, PhCat, PhForkKnife, PhNote, PhGear, PhCaretRight } from '@phosphor-icons/vue'
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
  { label: 'nav.expenses', sub: 'moreSheet.expensesSub', icon: PhWallet, action: () => navigate('/expenses'), disabled: false, highlight: true },
  { label: 'nav.cats', sub: 'moreSheet.catsSub', icon: PhCat, action: () => navigate('/pets'), disabled: false, highlight: false },
  { label: 'nav.meals', sub: 'moreSheet.mealsSub', icon: PhForkKnife, action: () => navigate('/food'), disabled: false, highlight: false },
  { label: 'nav.notes', sub: 'moreSheet.notesSub', icon: PhNote, action: () => navigate('/notes'), disabled: false, highlight: false },
  { label: 'nav.settings', sub: 'moreSheet.settingsSub', icon: PhGear, action: () => navigate('/household'), disabled: false, highlight: false },
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
            <h2 class="more-sheet__title">{{ t('moreSheet.title') }}</h2>
            <ul class="more-sheet__list">
              <li
                v-for="entry in entries"
                :key="entry.label"
                class="more-sheet__item"
                :class="{ 'more-sheet__item--disabled': entry.disabled }"
                @click="entry.action?.()"
              >
                <span class="more-sheet__icon-tile" :class="{ 'more-sheet__icon-tile--accent': entry.highlight }">
                  <component :is="entry.icon" :size="20" />
                </span>
                <div class="more-sheet__text">
                  <span class="more-sheet__label">{{ t(entry.label) }}</span>
                  <span class="more-sheet__sub">{{ t(entry.sub) }}</span>
                </div>
                <PhCaretRight :size="16" class="more-sheet__chevron" />
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
  margin: 0 auto var(--space-3);
}

.more-sheet__title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-lg);
  margin: 0 0 var(--space-3);
  color: var(--ink);
}

.more-sheet__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
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
  opacity: 0.5;
  pointer-events: none;
  cursor: default;
}

.more-sheet__icon-tile {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--chip);
  color: var(--ink);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.more-sheet__icon-tile--accent {
  background: var(--acc-soft);
  color: var(--acc);
}

.more-sheet__text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.more-sheet__label {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
}

.more-sheet__sub {
  font-size: var(--text-xs);
  color: var(--sub);
}

.more-sheet__chevron {
  color: var(--sub);
  flex-shrink: 0;
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
