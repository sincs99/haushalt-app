<script setup lang="ts">
import { watch, onUnmounted } from 'vue'
import { useAuthStore } from './stores/auth'
import { useShoppingStore } from './stores/shopping'
import { useTodosStore } from './stores/todos'
import { useExpensesStore } from './stores/expenses'
import { useSettlementsStore } from './stores/settlements'
import { useChoresStore } from './stores/chores'
import { useSocket } from './composables/useSocket'
import { useConnectivity } from './composables/useConnectivity'
import { useToast } from './composables/useToast'
import { ShoppingCart, ListChecks, Wallet, Home, Brush, WifiOff, CheckCircle2, AlertCircle, Info } from 'lucide-vue-next'

const { isOnline } = useConnectivity()
const { toasts } = useToast()
const authStore = useAuthStore()
const shoppingStore = useShoppingStore()
const todosStore = useTodosStore()
const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const choresStore = useChoresStore()
const { connect, joinHousehold, leaveHousehold, on, off, onReconnect, offReconnect, disconnect } = useSocket()

// Socket-Event-Binding: Watch auf Token + HouseholdId
watch(
  () => [authStore.token, authStore.currentHouseholdId] as const,
  (newValue, oldValue) => {
    const [token, householdId] = newValue ?? [null, null]
    const [, oldHouseholdId] = oldValue ?? [null, null]

    // IMMER zuerst alle Listener entfernen (idempotent, schadet nicht wenn nicht vorhanden)
    off('shopping_item_created', shoppingStore.handleItemCreated)
    off('shopping_item_updated', shoppingStore.handleItemUpdated)
    off('shopping_item_deleted', shoppingStore.handleItemDeleted)
    off('todo_created', todosStore.handleTodoCreated)
    off('todo_updated', todosStore.handleTodoUpdated)
    off('todo_deleted', todosStore.handleTodoDeleted)
    off('expense_created', expensesStore.handleExpenseCreated)
    off('expense_updated', expensesStore.handleExpenseUpdated)
    off('expense_deleted', expensesStore.handleExpenseDeleted)
    off('settlement_created', settlementsStore.handleSettlementCreated)
    off('settlement_deleted', settlementsStore.handleSettlementDeleted)
    off('chore_created', choresStore.handleChoreCreated)
    off('chore_updated', choresStore.handleChoreUpdated)
    off('chore_deleted', choresStore.handleChoreDeleted)
    off('chore_assignment_created', choresStore.handleAssignmentCreated)
    off('chore_assignment_updated', choresStore.handleAssignmentUpdated)

    // Wenn Token weg (Logout): Socket disconnecten
    if (!token) {
      disconnect()
      return
    }

    connect(token)

    // Alten Room verlassen
    if (oldHouseholdId && oldHouseholdId !== householdId) {
      leaveHousehold(oldHouseholdId)
    }

    if (householdId) {
      // Stores leeren bei Household-Wechsel
      if (oldHouseholdId && oldHouseholdId !== householdId) {
        shoppingStore.items = []
        todosStore.items = []
        todosStore.members = []
        expensesStore.expenses = []
        expensesStore.balances = null
        expensesStore.members = []
        settlementsStore.settlements = []
        choresStore.chores = []
        choresStore.assignments = []
        choresStore.members = []
      }

      joinHousehold(householdId)

      // Neue Listener binden
      on('shopping_item_created', shoppingStore.handleItemCreated)
      on('shopping_item_updated', shoppingStore.handleItemUpdated)
      on('shopping_item_deleted', shoppingStore.handleItemDeleted)
      on('todo_created', todosStore.handleTodoCreated)
      on('todo_updated', todosStore.handleTodoUpdated)
      on('todo_deleted', todosStore.handleTodoDeleted)
      on('expense_created', expensesStore.handleExpenseCreated)
      on('expense_updated', expensesStore.handleExpenseUpdated)
      on('expense_deleted', expensesStore.handleExpenseDeleted)
      on('settlement_created', settlementsStore.handleSettlementCreated)
      on('settlement_deleted', settlementsStore.handleSettlementDeleted)
      on('chore_created', choresStore.handleChoreCreated)
      on('chore_updated', choresStore.handleChoreUpdated)
      on('chore_deleted', choresStore.handleChoreDeleted)
      on('chore_assignment_created', choresStore.handleAssignmentCreated)
      on('chore_assignment_updated', choresStore.handleAssignmentUpdated)

      shoppingStore.fetchItems()
      todosStore.fetchTodos()
      expensesStore.fetchExpenses()
      expensesStore.fetchBalances()
      settlementsStore.fetchAll()
      choresStore.fetchChores()
      choresStore.fetchAssignments()
    }
  },
  { immediate: true }
)

// Reconnect-Handler: Room neu beitreten + Daten nachladen
function handleReconnect() {
  const householdId = authStore.currentHouseholdId
  if (householdId) {
    joinHousehold(householdId)
    shoppingStore.fetchItems()
    todosStore.fetchTodos()
    expensesStore.fetchExpenses()
    expensesStore.fetchBalances()
    settlementsStore.fetchAll()
    choresStore.fetchChores()
    choresStore.fetchAssignments()
  }
}

onReconnect(handleReconnect)

onUnmounted(() => {
  off('shopping_item_created', shoppingStore.handleItemCreated)
  off('shopping_item_updated', shoppingStore.handleItemUpdated)
  off('shopping_item_deleted', shoppingStore.handleItemDeleted)
  off('todo_created', todosStore.handleTodoCreated)
  off('todo_updated', todosStore.handleTodoUpdated)
  off('todo_deleted', todosStore.handleTodoDeleted)
  off('expense_created', expensesStore.handleExpenseCreated)
  off('expense_updated', expensesStore.handleExpenseUpdated)
  off('expense_deleted', expensesStore.handleExpenseDeleted)
  off('settlement_created', settlementsStore.handleSettlementCreated)
  off('settlement_deleted', settlementsStore.handleSettlementDeleted)
  off('chore_created', choresStore.handleChoreCreated)
  off('chore_updated', choresStore.handleChoreUpdated)
  off('chore_deleted', choresStore.handleChoreDeleted)
  off('chore_assignment_created', choresStore.handleAssignmentCreated)
  off('chore_assignment_updated', choresStore.handleAssignmentUpdated)
  offReconnect(handleReconnect)
  disconnect()
})
</script>

<template>
  <!-- Offline-Banner -->
  <div v-if="!isOnline" class="offline-banner" role="alert">
    <WifiOff :size="16" />
    {{ $t('offline.banner') }}
  </div>

  <!-- App-Shell (authentifiziert) -->
  <div v-if="authStore.isAuthenticated" class="app-shell">

    <!-- Desktop Top-Bar (≥768px sichtbar) -->
    <header class="top-bar">
      <div class="top-bar__content">
        <span class="top-bar__brand"><Home :size="20" /> {{ $t('nav.brand') }}</span>
        <nav class="top-bar__nav">
          <router-link to="/shopping" class="top-bar__link" active-class="top-bar__link--active">
            <ShoppingCart :size="18" /> {{ $t('nav.shopping') }}
          </router-link>
          <router-link to="/todos" class="top-bar__link" active-class="top-bar__link--active">
            <ListChecks :size="18" /> {{ $t('nav.todos') }}
          </router-link>
          <router-link to="/expenses" class="top-bar__link" active-class="top-bar__link--active">
            <Wallet :size="18" /> {{ $t('nav.expenses') }}
          </router-link>
          <router-link to="/chores" class="top-bar__link" active-class="top-bar__link--active">
            <Brush :size="18" /> {{ $t('nav.chores') }}
          </router-link>
          <router-link to="/household" class="top-bar__link" active-class="top-bar__link--active">
            <Home :size="18" /> {{ $t('nav.household') }}
          </router-link>
        </nav>
        <div class="top-bar__right">
          <!-- Household-Wechsel (nur bei >1 Haushalt) -->
          <select
            v-if="authStore.households.length > 1"
            :value="authStore.currentHouseholdId"
            @change="authStore.switchHousehold(($event.target as HTMLSelectElement).value)"
            class="household-select"
          >
            <option v-for="h in authStore.households" :key="h.id" :value="h.id">
              {{ h.name }}
            </option>
          </select>
          <span class="top-bar__user">{{ authStore.user?.display_name }}</span>
          <button class="top-bar__logout" @click="authStore.logout()">{{ $t('auth.logout') }}</button>
        </div>
      </div>
    </header>

    <!-- Hauptinhalt -->
    <main class="app-content">
      <router-view />
    </main>

    <!-- Mobile Bottom-Tab-Bar (<768px sichtbar) -->
    <nav class="tab-bar" :aria-label="$t('nav.brand')">
      <router-link to="/shopping" class="tab-bar__tab" active-class="tab-bar__tab--active">
        <ShoppingCart :size="22" class="tab-bar__icon" />
        <span class="tab-bar__label">{{ $t('nav.shopping') }}</span>
      </router-link>
      <router-link to="/todos" class="tab-bar__tab" active-class="tab-bar__tab--active">
        <ListChecks :size="22" class="tab-bar__icon" />
        <span class="tab-bar__label">{{ $t('nav.todos') }}</span>
      </router-link>
      <router-link to="/expenses" class="tab-bar__tab" active-class="tab-bar__tab--active">
        <Wallet :size="22" class="tab-bar__icon" />
        <span class="tab-bar__label">{{ $t('nav.expenses') }}</span>
      </router-link>
      <router-link to="/chores" class="tab-bar__tab" active-class="tab-bar__tab--active">
        <Brush :size="22" class="tab-bar__icon" />
        <span class="tab-bar__label">{{ $t('nav.chores') }}</span>
      </router-link>
      <router-link to="/household" class="tab-bar__tab" active-class="tab-bar__tab--active">
        <Home :size="22" class="tab-bar__icon" />
        <span class="tab-bar__label">{{ $t('nav.household') }}</span>
      </router-link>
    </nav>
  </div>

  <!-- Unauthenticated: nur Router-View (Login/Register) -->
  <router-view v-else />

  <!-- Toast-Benachrichtigungen -->
  <Teleport to="body">
    <div class="toast-container" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          :class="['toast', `toast--${toast.type}`]"
          role="status"
        >
          <CheckCircle2 v-if="toast.type === 'success'" :size="16" />
          <AlertCircle v-if="toast.type === 'error'" :size="16" />
          <Info v-if="toast.type === 'info'" :size="16" />
          {{ toast.text }}
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
/* ── Offline-Banner ── */
.offline-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background-color: var(--color-warning);
  color: var(--color-neutral-900);
  text-align: center;
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-sm);
  line-height: var(--line-height-normal);
  box-shadow: var(--shadow-overlay);
}

/* ── Desktop Top-Bar ── */
.top-bar {
  display: none;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-neutral-200);
  position: sticky;
  top: 0;
  z-index: 100;
}

@media (min-width: 768px) {
  .top-bar {
    display: block;
  }
}

.top-bar__content {
  max-width: 640px;
  margin: 0 auto;
  padding: var(--space-2) var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.top-bar__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: var(--font-weight-bold);
  font-size: var(--text-lg);
  color: var(--color-primary);
}

.top-bar__nav {
  display: flex;
  gap: var(--space-1);
}

.top-bar__link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  text-decoration: none;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.top-bar__link:hover {
  background: var(--color-neutral-100);
  color: var(--color-text);
}

.top-bar__link--active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.top-bar__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.top-bar__user {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.top-bar__logout {
  padding: var(--space-1) var(--space-3);
  background: none;
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: background var(--transition-fast);
}

.top-bar__logout:hover {
  background: var(--color-neutral-100);
}

.household-select {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-neutral-300);
  background: var(--color-surface);
  font-size: var(--text-sm);
  cursor: pointer;
}

.household-select:focus-visible {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* ── App Content ── */
.app-content {
  max-width: 640px;
  margin: 0 auto;
  padding: var(--space-4);
  padding-bottom: calc(var(--space-4) + 64px);
}

@media (min-width: 768px) {
  .app-content {
    padding-bottom: var(--space-4);
  }
}

/* ── Mobile Bottom-Tab-Bar ── */
.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  background: var(--color-surface);
  border-top: 1px solid var(--color-neutral-200);
  padding-bottom: env(safe-area-inset-bottom, 0);
}

@media (min-width: 768px) {
  .tab-bar {
    display: none;
  }
}

.tab-bar__tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: var(--space-2) 0;
  min-height: 56px;
  text-decoration: none;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  transition: color var(--transition-fast);
}

.tab-bar__tab--active {
  color: var(--color-primary);
}

.tab-bar__icon {
  line-height: 1;
  width: 22px;
  height: 22px;
}

.tab-bar__label {
  font-weight: var(--font-weight-normal);
}

.tab-bar__tab--active .tab-bar__label {
  font-weight: var(--font-weight-medium);
}

/* ── Toast-Container ── */
.toast-container {
  position: fixed;
  bottom: calc(64px + env(safe-area-inset-bottom, 0) + var(--space-3));
  left: 50%;
  transform: translateX(-50%);
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  pointer-events: none;
  width: 90%;
  max-width: 400px;
}

@media (min-width: 768px) {
  .toast-container {
    bottom: var(--space-6);
  }
}

.toast {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  line-height: var(--line-height-normal);
  text-align: center;
  box-shadow: var(--shadow-overlay);
  pointer-events: auto;
}

.toast--error {
  background-color: var(--color-danger);
  color: var(--color-surface);
}

.toast--success {
  background-color: var(--color-success);
  color: var(--color-surface);
}

.toast--info {
  background-color: var(--color-primary);
  color: var(--color-surface);
}

/* ── Toast-Transitions ── */
.toast-enter-active {
  transition: all 0.3s ease-out;
}

.toast-leave-active {
  transition: all 0.25s ease-in;
}

.toast-enter-from {
  opacity: 0;
  transform: translateY(16px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.toast-move {
  transition: transform 0.25s ease;
}
</style>
