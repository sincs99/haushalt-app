<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import { PhHouse, PhCalendarDots, PhListChecks, PhShoppingBagOpen, PhDotsThreeCircle } from '@phosphor-icons/vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  syncStatus: string
  moreActive: boolean
}>()

const emit = defineEmits<{
  'toggle-more': []
}>()

const route = useRoute()
const { t } = useI18n()

const tabs = computed(() => [
  { to: '/dashboard', icon: PhHouse, label: t('nav.start'), key: 'dashboard' },
  { to: '/calendar', icon: PhCalendarDots, label: t('nav.calendar'), key: 'calendar' },
  { to: '/todos', icon: PhListChecks, label: t('nav.todos'), key: 'todos' },
  { to: '/shopping', icon: PhShoppingBagOpen, label: t('nav.shopping'), key: 'shopping' },
])

const isTabActive = (to: string) => route.path === to
</script>

<template>
  <nav class="bottom-nav" aria-label="Navigation">
    <router-link
      v-for="tab in tabs"
      :key="tab.key"
      :to="tab.to"
      class="bottom-nav__tab"
      :class="{ 'bottom-nav__tab--active': isTabActive(tab.to) }"
    >
      <component :is="tab.icon" :size="22" :weight="isTabActive(tab.to) ? 'fill' : 'regular'" class="bottom-nav__icon" />
      <span class="bottom-nav__label">{{ tab.label }}</span>
    </router-link>

    <button
      class="bottom-nav__tab"
      :class="{ 'bottom-nav__tab--active': moreActive }"
      @click="emit('toggle-more')"
    >
      <span class="bottom-nav__icon-wrap">
        <PhDotsThreeCircle :size="22" :weight="moreActive ? 'fill' : 'regular'" class="bottom-nav__icon" />
        <span
          class="bottom-nav__sync-dot sync-dot"
          :class="`sync-dot--${syncStatus}`"
          :aria-label="$t(`sync.${syncStatus}`)"
          role="status"
        />
      </span>
      <span class="bottom-nav__label">{{ t('nav.more') }}</span>
    </button>
  </nav>
</template>

<style scoped>
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  background: var(--nav);
  border-top: 1px solid var(--line);
  padding-bottom: env(safe-area-inset-bottom, 0);
}

@media (min-width: 768px) {
  .bottom-nav {
    display: none;
  }
}

.bottom-nav__tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: var(--space-2) 0;
  min-height: 56px;
  text-decoration: none;
  color: var(--sub);
  font-size: var(--text-xs);
  transition: color var(--transition-fast);
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
}

.bottom-nav__tab--active {
  color: var(--acc);
}

.bottom-nav__icon {
  line-height: 1;
  width: 22px;
  height: 22px;
}

.bottom-nav__icon-wrap {
  position: relative;
  display: inline-flex;
}

.bottom-nav__sync-dot {
  position: absolute;
  top: -2px;
  right: -4px;
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
}

.bottom-nav__label {
  font-weight: var(--font-weight-normal);
}

.bottom-nav__tab--active .bottom-nav__label {
  font-weight: var(--font-weight-medium);
}

/* Sync-Dot Farben (gleich wie App.vue Topbar) */
.sync-dot--connected {
  background-color: var(--ok);
}

.sync-dot--reconnecting {
  background-color: var(--color-warning);
  animation: sync-pulse 1.5s ease-in-out infinite;
}

.sync-dot--offline {
  background-color: var(--sub);
}

@keyframes sync-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
