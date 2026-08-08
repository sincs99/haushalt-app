<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { usePollsStore } from '../stores/polls'
import { useTodosStore } from '../stores/todos'
import { useChoresStore } from '../stores/chores'
import { useTasksStore } from '../stores/tasks'
import { usePetsStore } from '../stores/pets'
import { formatRappen } from '../utils/money'
import { PhShoppingBagOpen, PhListChecks, PhWallet, PhCalendarDots, PhCat, PhForkKnife, PhCaretRight } from '@phosphor-icons/vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseCheckCircle from '../components/ui/BaseCheckCircle.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import { categoryColors } from '../utils/categoryColors'
import type { DashboardTodoItem, DashboardEventItem } from '../types'

const router = useRouter()
const { t, locale } = useI18n()
const authStore = useAuthStore()
const dashboardStore = useDashboardStore()
const todosStore = useTodosStore()
const choresStore = useChoresStore()
const tasksStore = useTasksStore()
const pollsStore = usePollsStore()
const petsStore = usePetsStore()

// Polls laden
pollsStore.fetchPolls('offen')

// Pets-Fütterungsstatus laden
petsStore.fetchFeedingStatus()

// ── Pets Feeding Widget ──
const petsFedCount = computed(() => {
  let fed = 0
  for (const s of petsStore.feedingStatus) {
    if (s.morning) fed++
    if (s.evening) fed++
  }
  return fed
})

const petsTotalSlots = computed(() => petsStore.feedingStatus.length * 2)

// ── Open Poll Count ──
const openPollCount = computed(() => pollsStore.openPolls.length)

// ── Open Meal Poll Count ──
const openMealPollCount = computed(() => pollsStore.openMealPolls.length)

// ── Greeting ──
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) return t('dashboard.greetingMorning')
  if (hour < 18) return t('dashboard.greetingAfternoon')
  return t('dashboard.greetingEvening')
})

const firstName = computed(() => {
  const name = authStore.user?.display_name ?? ''
  return name.split(' ')[0]
})

const formattedDate = computed(() => {
  const intlLocale = locale.value === 'de' ? 'de-CH' : 'en-GB'
  return new Intl.DateTimeFormat(intlLocale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date())
})

// ── Data shortcut ──
const data = computed(() => dashboardStore.data)

// ── Combined Tasks (max 3, Todos first) ──
const combinedTasks = computed<DashboardTodoItem[]>(() => {
  if (!data.value) return []

  const todoItems = data.value.todos.items.slice(0, 3)
  const remaining = 3 - todoItems.length

  const choreItems: DashboardTodoItem[] = remaining > 0
    ? data.value.chores.items.slice(0, remaining).map(c => ({
        id: c.id,
        title: c.title,
        due_date: null,
        is_overdue: false,
        type: 'chore' as const,
      }))
    : []

  return [...todoItems, ...choreItems].slice(0, 3)
})

// ── Overdue Badge ──
const overdueBadge = computed(() => {
  if (!data.value || data.value.todos.overdue_count === 0) return ''
  return t('dashboard.overdueCount', { n: data.value.todos.overdue_count })
})

// ── Finance ──
const financeText = computed(() => {
  if (!data.value) return ''
  const saldo = data.value.finance.saldo_rappen
  if (saldo > 0) return t('dashboard.youGet', { amount: formatRappen(saldo, data.value.finance.currency) })
  if (saldo < 0) return t('dashboard.youOwe', { amount: formatRappen(Math.abs(saldo), data.value.finance.currency) })
  return t('dashboard.settled')
})

const financeClass = computed(() => {
  if (!data.value) return ''
  const saldo = data.value.finance.saldo_rappen
  if (saldo > 0) return 'finance--positive'
  if (saldo < 0) return 'finance--negative'
  return ''
})

// ── Events ──
const todayEvents = computed(() => {
  if (!data.value) return []
  return data.value.events.items
})

function formatEventTime(item: DashboardEventItem): string {
  if (item.all_day) return t('calendar.allDay')
  const date = new Date(item.starts_at)
  return date.toLocaleTimeString(locale.value === 'de' ? 'de-CH' : 'en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ── Handlers ──
async function handleToggleTask(item: DashboardTodoItem) {
  if (item.type === 'todo') {
    await todosStore.toggleDone(item.id)
  } else {
    await choresStore.completeAssignment(item.id)
  }
  dashboardStore.invalidate()
  tasksStore.invalidate()
}
</script>

<template>
  <div class="dashboard">
    <!-- Greeting -->
    <div class="greeting">
      <h1 class="greeting__title">{{ greeting }}, {{ firstName }}</h1>
      <p class="greeting__date">{{ formattedDate }}</p>
    </div>

    <!-- Loading Skeleton -->
    <template v-if="dashboardStore.loading && !dashboardStore.data">
      <BaseCard>
        <div class="skeleton-list">
          <BaseSkeleton width="40%" height="18px" />
          <BaseSkeleton width="100%" height="14px" />
          <BaseSkeleton width="80%" height="14px" />
          <BaseSkeleton width="60%" height="14px" />
        </div>
      </BaseCard>
      <BaseCard>
        <BaseSkeleton width="30%" height="18px" />
        <BaseSkeleton width="50%" height="24px" />
      </BaseCard>
      <BaseCard>
        <BaseSkeleton width="30%" height="18px" />
        <BaseSkeleton width="40%" height="24px" />
      </BaseCard>
    </template>

    <template v-else-if="dashboardStore.data">
      <!-- Karte: Heute (Events) -->
      <BaseCard class="clickable-card" @click="router.push('/calendar')">
        <h2 class="card-title">
          <PhCalendarDots :size="18" style="vertical-align: -2px; margin-right: 4px" />
          {{ t('calendar.today') }}
        </h2>
        <ul v-if="todayEvents.length > 0" class="event-list">
          <li v-for="ev in todayEvents" :key="ev.id" class="event-item">
            <span
              class="event-item__bar"
              :style="{ backgroundColor: categoryColors[ev.category as keyof typeof categoryColors] || '#8B8B8B' }"
            />
            <span class="event-item__time">{{ formatEventTime(ev) }}</span>
            <span class="event-item__title">{{ ev.title }}</span>
          </li>
        </ul>
        <p v-else class="card-empty">{{ t('calendar.noEventsToday') }}</p>
      </BaseCard>

      <!-- Karte: Abstimmungen -->
      <BaseCard v-if="openPollCount > 0" class="clickable-card" @click="router.push('/calendar')">
        <h2 class="card-title">{{ t('polls.title') }}</h2>
        <p class="card-stat">{{ t('polls.open') }}: {{ openPollCount }}</p>
      </BaseCard>

      <!-- Karte: Aufgaben (Todos + Chores) -->
      <BaseCard>
        <h2 class="card-title">{{ t('dashboard.tasks') }}</h2>
        <p v-if="overdueBadge" class="overdue-badge">{{ overdueBadge }}</p>
        <ul class="task-list">
          <li v-for="item in combinedTasks" :key="item.id" class="task-item">
            <BaseCheckCircle
              :checked="false"
              @toggle="handleToggleTask(item)"
            />
            <span
              class="task-item__title"
              :class="{ 'task-item__title--overdue': item.is_overdue }"
            >
              {{ item.title }}
            </span>
          </li>
        </ul>
        <p v-if="combinedTasks.length === 0" class="card-empty">{{ t('dashboard.noTasks') }}</p>
      </BaseCard>

      <!-- Karte: Einkauf -->
      <BaseCard class="clickable-card" @click="router.push('/shopping')">
        <h2 class="card-title">{{ t('dashboard.shopping') }}</h2>
        <p class="card-stat">{{ t('dashboard.shoppingOpen', { n: data!.shopping.open_count }) }}</p>
        <p class="card-items" v-if="data!.shopping.top_items.length">
          {{ data!.shopping.top_items.join(', ') }}
        </p>
      </BaseCard>

      <!-- Karte: Katzen-Fütterung -->
      <BaseCard v-if="petsStore.feedingStatus.length > 0" class="clickable-card" @click="router.push('/pets')">
        <h2 class="card-title">
          <PhCat :size="18" style="vertical-align: -2px; margin-right: 4px" />
          {{ t('pets.title') }}
        </h2>
        <p class="card-stat">{{ t('pets.feedingWidget', { fed: petsFedCount, total: petsTotalSlots }) }}</p>
      </BaseCard>

      <!-- Karte: Essen-Abstimmung (nur wenn offene Meal-Polls existieren) -->
      <BaseCard v-if="openMealPollCount > 0" class="clickable-card" @click="router.push('/food')">
        <div class="dash-card__row">
          <PhForkKnife :size="20" class="dash-card__icon" />
          <div class="dash-card__text">
            <span class="dash-card__label">{{ t('food.whatToEat') }}</span>
            <span class="dash-card__sub">{{ t('food.openPollCount', openMealPollCount) }}</span>
          </div>
          <PhCaretRight :size="16" class="dash-card__chevron" />
        </div>
      </BaseCard>

      <!-- Karte: Finanzen -->
      <BaseCard class="clickable-card" @click="router.push('/expenses')">
        <h2 class="card-title">{{ t('dashboard.finance') }}</h2>
        <p class="finance-amount" :class="financeClass">
          {{ financeText }}
        </p>
      </BaseCard>

      <!-- Quick Actions -->
      <div class="quick-actions">
        <router-link to="/shopping?new=1" class="quick-chip">
          <PhShoppingBagOpen :size="16" /> {{ t('dashboard.quickShopping') }}
        </router-link>
        <router-link to="/todos?new=1" class="quick-chip">
          <PhListChecks :size="16" /> {{ t('dashboard.quickTask') }}
        </router-link>
        <router-link to="/expenses?new=1" class="quick-chip">
          <PhWallet :size="16" /> {{ t('dashboard.quickExpense') }}
        </router-link>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Greeting ── */
.greeting__title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  color: var(--ink);
  margin: 0;
}

.greeting__date {
  font-size: var(--text-sm);
  color: var(--sub);
  margin: var(--space-1) 0 0;
}

/* ── Card Titles ── */
.card-title {
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-3) 0;
  color: var(--ink);
}

/* ── Task List ── */
.task-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.task-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.task-item__title--overdue {
  color: var(--color-danger);
}

/* ── Overdue Badge ── */
.overdue-badge {
  font-size: var(--text-xs);
  color: var(--color-danger);
  margin: 0 0 var(--space-2) 0;
}

/* ── Card Empty ── */
.card-empty {
  font-size: var(--text-sm);
  color: var(--sub);
  margin: 0;
}

/* ── Clickable Card ── */
.clickable-card {
  cursor: pointer;
}

@media (hover: hover) {
  .clickable-card {
    transition: transform var(--transition-fast);
  }

  .clickable-card:hover {
    transform: scale(1.01);
  }
}

/* ── Card Stat ── */
.card-stat {
  font-size: var(--text-lg);
  font-weight: var(--font-weight-bold);
  color: var(--ink);
  margin: 0;
}

.card-items {
  font-size: var(--text-sm);
  color: var(--sub);
  margin: var(--space-1) 0 0;
}

/* ── Finance ── */
.finance-amount {
  font-size: var(--text-lg);
  font-weight: var(--font-weight-bold);
  margin: 0;
}

.finance--positive {
  color: var(--ok);
}

.finance--negative {
  color: var(--color-danger);
}

/* ── Quick Actions ── */
.quick-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.quick-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--chip);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  color: var(--ink);
  text-decoration: none;
  transition: background var(--transition-fast);
}

.quick-chip:hover {
  background: var(--line);
}

/* ── Event-Liste (Dashboard) ── */
.event-list {
  list-style: none;
  padding: 0;
  margin: var(--space-2) 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.event-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 28px;
}

.event-item__bar {
  width: 3px;
  height: 20px;
  border-radius: 2px;
  flex-shrink: 0;
}

.event-item__time {
  font-size: var(--text-xs);
  color: var(--sub);
  min-width: 48px;
  flex-shrink: 0;
}

.event-item__title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Skeleton ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* ── Dash Card Row (Meal Poll) ── */
.dash-card__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.dash-card__icon {
  color: var(--acc);
  flex-shrink: 0;
}

.dash-card__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dash-card__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.dash-card__sub {
  font-size: var(--text-xs);
  color: var(--sub);
}

.dash-card__chevron {
  color: var(--sub);
  flex-shrink: 0;
}
</style>
