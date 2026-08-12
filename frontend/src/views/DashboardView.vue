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
import { useCalendarStore } from '../stores/calendar'
import { formatRappen } from '../utils/money'
import { PhShoppingBagOpen, PhListChecks, PhBroom, PhWallet, PhCalendarDots, PhCat, PhForkKnife, PhCaretRight, PhPawPrint, PhBell } from '@phosphor-icons/vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseCheckCircle from '../components/ui/BaseCheckCircle.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import type { DashboardTodoItem, DashboardEventItem, DashboardPetCareItem, DashboardReminderItem } from '../types'

const router = useRouter()
const { t, locale } = useI18n()
const authStore = useAuthStore()
const dashboardStore = useDashboardStore()
const todosStore = useTodosStore()
const choresStore = useChoresStore()
const tasksStore = useTasksStore()
const pollsStore = usePollsStore()
const petsStore = usePetsStore()
const calendarStore = useCalendarStore()

// Kalender laden für Farbzuordnung
calendarStore.fetchCalendars()

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

// ── Pet Care Due ──
const petCareDue = computed(() => data.value?.pet_care_due ?? [])

function formatPetCareDue(item: DashboardPetCareItem): string {
  const dueDate = new Date(item.next_due_at + 'T00:00:00')
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const diffDays = Math.round((dueDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return t('dashboard.petCareOverdue')
  if (diffDays === 0) return t('dashboard.petCareDueToday')
  return t('dashboard.petCareDueIn', { n: diffDays })
}

function formatReminderDate(isoString: string): string {
  const d = new Date(isoString)
  const intlLocale = locale.value === 'de' ? 'de-CH' : 'en-GB'
  return new Intl.DateTimeFormat(intlLocale, {
    day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(d)
}
</script>

<template>
  <div class="dashboard">
    <!-- Greeting -->
    <div class="greeting">
      <BaseAvatar
        :name="authStore.user?.display_name ?? ''"
        :user-id="authStore.user?.id ?? ''"
        size="md"
      />
      <div class="greeting__text">
        <h1 class="greeting__title">{{ greeting }}, {{ firstName }}</h1>
        <p class="greeting__date">{{ formattedDate }}</p>
      </div>
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
              :style="{ backgroundColor: calendarStore.getCalendarColor(ev.calendar_id) }"
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
          <li
            v-for="item in combinedTasks"
            :key="item.id"
            class="task-item"
            @click="router.push(item.type === 'chore' ? '/chores' : '/todos')"
          >
            <BaseCheckCircle
              :checked="false"
              @toggle="handleToggleTask(item)"
              @click.stop
            />
            <component
              :is="item.type === 'chore' ? PhBroom : PhListChecks"
              :size="14"
              class="task-item__type-icon"
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

      <!-- Karte: Katzen-Pflegetermine -->
      <BaseCard v-if="petCareDue.length > 0">
        <h2 class="card-title">
           <PhPawPrint :size="18" style="vertical-align: -2px; margin-right: 4px" />
           {{ t('dashboard.petCareTitle') }}
        </h2>
        <ul class="pet-care-list">
          <li
            v-for="item in petCareDue"
            :key="item.id"
            class="pet-care-item"
            :class="{ 'pet-care-item--overdue': item.is_overdue }"
            @click="router.push('/pets/' + item.pet_id)"
          >
            <div class="pet-care-item__info">
              <span class="pet-care-item__name">{{ item.name }}</span>
              <span class="pet-care-item__pet">{{ item.pet_name }}</span>
            </div>
            <span
              class="pet-care-item__due"
              :class="{
                'pet-care-item__due--overdue': item.is_overdue,
                'pet-care-item__due--today': !item.is_overdue && formatPetCareDue(item) === t('dashboard.petCareDueToday')
              }"
            >
              {{ formatPetCareDue(item) }}
            </span>
          </li>
        </ul>
      </BaseCard>

      <!-- Upcoming Reminders -->
      <BaseCard v-if="data && data.upcoming_reminders && data.upcoming_reminders.length > 0" class="dashboard-card">
        <div class="card-header">
          <PhBell :size="20" weight="duotone" />
          <span class="card-title">{{ $t('dashboard.remindersTitle') }}</span>
        </div>
        <ul class="card-list">
          <li
            v-for="reminder in data.upcoming_reminders"
            :key="reminder.id"
            class="reminder-item"
            @click="router.push('/todos')"
          >
            <div class="reminder-item__content">
              <span class="reminder-item__time">{{ formatReminderDate(reminder.remind_at) }}</span>
              <span class="reminder-item__title">{{ reminder.todo_title }}</span>
            </div>
            <PhCaretRight :size="16" class="caret" />
          </li>
        </ul>
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
.greeting {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.greeting__text {
  min-width: 0;
}

.greeting__title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  color: var(--ink);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  gap: var(--space-2);
  cursor: pointer;
  padding: var(--space-1) 0;
  border-radius: var(--radius-sm);
  transition: opacity var(--transition-fast);
}

.task-item:active {
  opacity: 0.7;
}

.task-item__type-icon {
  flex-shrink: 0;
  color: var(--sub);
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

/* ── Pet Care Widget ── */
.pet-care-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.pet-care-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}

@media (hover: hover) {
  .pet-care-item:hover {
    background: var(--line);
  }
}

.pet-care-item:active {
  background: var(--line);
}

.pet-care-item--overdue {
  border-left: 3px solid var(--color-danger);
  padding-left: var(--space-2);
}

.pet-care-item__info {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.pet-care-item__name {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-care-item__pet {
  font-size: var(--text-xs);
  color: var(--sub);
}

.pet-care-item__due {
  font-size: var(--text-xs);
  color: var(--sub);
  flex-shrink: 0;
  margin-left: var(--space-3);
}

.pet-care-item__due--overdue {
  color: var(--color-danger);
  font-weight: var(--font-weight-semibold);
}

.pet-care-item__due--today {
  color: var(--color-warning);
  font-weight: var(--font-weight-semibold);
}

/* ── Reminder Widget ── */
.reminder-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
  cursor: pointer;
  border-bottom: 1px solid var(--line);
}

.reminder-item:last-child {
  border-bottom: none;
}

.reminder-item:active {
  opacity: 0.7;
}

.reminder-item__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.reminder-item__time {
  font-size: var(--text-sm);
  color: var(--acc);
  font-weight: var(--font-weight-medium);
}

.reminder-item__title {
  font-size: var(--text-sm);
  color: var(--sub);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
