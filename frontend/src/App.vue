<script setup lang="ts">
import { watch, onUnmounted, computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useShoppingStore } from './stores/shopping'
import { useTodosStore } from './stores/todos'
import { useExpensesStore } from './stores/expenses'
import { useSettlementsStore } from './stores/settlements'
import { useChoresStore } from './stores/chores'
import { useFinanceStore } from './stores/finance'
import { useDashboardStore } from './stores/dashboard'
import { usePollsStore } from './stores/polls'
import { usePetsStore } from './stores/pets'
import { usePlantsStore } from './stores/plants'
import { resetHouseholdScopedStores } from './stores/householdScope'
import { useSocket } from './composables/useSocket'
import { useConnectivity } from './composables/useConnectivity'
import BaseAvatar from './components/ui/BaseAvatar.vue'
import BaseButton from './components/ui/BaseButton.vue'
import BaseDialog from './components/ui/BaseDialog.vue'
import TheBottomNav from './components/TheBottomNav.vue'
import MoreSheet from './components/MoreSheet.vue'
import { useToast } from './composables/useToast'
import { syncPushSubscription } from './services/pushService'
import { BADGE_EVENTS, refreshAppBadge, refreshAppBadgeSoon, setAppBadgeHousehold } from './composables/useAppBadge'
import { useI18n } from 'vue-i18n'
import { PhShoppingBagOpen, PhListChecks, PhWallet, PhHouse, PhCalendarDots, PhWifiSlash, PhCheckCircle, PhWarningCircle, PhInfo, PhDotsThreeCircle } from '@phosphor-icons/vue'

const route = useRoute()
const { isOnline } = useConnectivity()
const { toasts, dismissToast } = useToast()
const moreOpen = ref(false)

// Abmelden: offline nachfragen, weil Anmelden erst wieder mit Netz geht
const logoutDialogOpen = ref(false)
function requestLogout() {
  if (isOnline.value) authStore.logout({ reason: 'user' })
  else logoutDialogOpen.value = true
}
function confirmLogout() {
  logoutDialogOpen.value = false
  authStore.logout({ reason: 'user' })
}
// „Mehr“ ist aktiv für alle Seiten, die keinen eigenen Tab haben (inkl. Detailseiten)
const TAB_ROUTES = ['/dashboard', '/calendar', '/todos', '/shopping']
const moreActive = computed(() =>
  moreOpen.value || !TAB_ROUTES.some((p) => route.path === p || route.path.startsWith(`${p}/`))
)
const authStore = useAuthStore()
const shoppingStore = useShoppingStore()
const todosStore = useTodosStore()
const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const choresStore = useChoresStore()
const financeStore = useFinanceStore()
const dashboardStore = useDashboardStore()
const pollsStore = usePollsStore()
const petsStore = usePetsStore()
const plantsStore = usePlantsStore()
const { updateToken, setTokenRefresher, joinHousehold, leaveHousehold, on, off, onReconnect, offReconnect, disconnect, isConnected } = useSocket()

// Trennt der Server den Socket wegen Token-Ablauf, holt sich der Socket hierüber ein frisches Token
setTokenRefresher(() => authStore.refreshForSocket())

// Push-Subscription dem eingeloggten User + aktueller Sprache zuordnen
const { locale } = useI18n()
watch(
  () => [authStore.user?.id, locale.value] as const,
  ([userId]) => {
    if (userId) syncPushSubscription()
  },
  { immediate: true },
)

// Sync-Status für Indikator
const syncStatus = computed(() => {
  if (!isOnline.value) return 'offline'
  if (isConnected.value) return 'connected'
  return 'reconnecting'
})

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
    off('shopping_list_created', shoppingStore.handleListCreated)
    off('shopping_list_updated', shoppingStore.handleListUpdated)
    off('shopping_list_deleted', shoppingStore.handleListDeleted)
    off('shopping_items_bulk_updated', shoppingStore.handleBulkUpdated)
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
    off('budget_updated', financeStore.handleBudgetUpdated)
    off('budget_deleted', financeStore.handleBudgetDeleted)
    off('recurring_bill_created', financeStore.handleBillCreated)
    off('recurring_bill_updated', financeStore.handleBillUpdated)
    off('recurring_bill_deleted', financeStore.handleBillDeleted)
    off('recurring_bill_booked', financeStore.handleBillBooked)
    off('household_updated', authStore.handleHouseholdUpdated)
    off('household_member_joined', authStore.handleMemberJoined)
    off('household_member_left', authStore.handleMemberLeft)
    off('household_member_removed', authStore.handleMemberRemoved)
    off('budget_updated', dashboardStore.invalidate)
    off('budget_deleted', dashboardStore.invalidate)
    off('recurring_bill_booked', dashboardStore.invalidate)
    off('todo_created', dashboardStore.invalidate)
    off('todo_updated', dashboardStore.invalidate)
    off('todo_deleted', dashboardStore.invalidate)
    off('shopping_item_created', dashboardStore.invalidate)
    off('shopping_item_updated', dashboardStore.invalidate)
    off('shopping_item_deleted', dashboardStore.invalidate)
    off('shopping_list_created', dashboardStore.invalidate)
    off('shopping_list_deleted', dashboardStore.invalidate)
    off('shopping_items_bulk_updated', dashboardStore.invalidate)
    off('expense_created', dashboardStore.invalidate)
    off('expense_updated', dashboardStore.invalidate)
    off('expense_deleted', dashboardStore.invalidate)
    off('settlement_created', dashboardStore.invalidate)
    off('settlement_deleted', dashboardStore.invalidate)
    off('chore_assignment_created', dashboardStore.invalidate)
    off('chore_assignment_updated', dashboardStore.invalidate)
    off('event_created', dashboardStore.invalidate)
    off('event_updated', dashboardStore.invalidate)
    off('event_deleted', dashboardStore.invalidate)
    off('poll_created', pollsStore.handleSocketCreated)
    off('poll_voted', pollsStore.handleSocketVoted)
    off('poll_decided', pollsStore.handleSocketDecided)
    off('poll_deleted', pollsStore.handleSocketDeleted)
    off('poll_decided', dashboardStore.invalidate)
    off('pet_care_task_created', petsStore.handleCareTaskCreated)
    off('pet_care_task_updated', petsStore.handleCareTaskUpdated)
    off('pet_care_task_deleted', petsStore.handleCareTaskDeleted)
    off('pet_care_task_created', dashboardStore.invalidate)
    off('pet_care_task_updated', dashboardStore.invalidate)
    off('pet_care_task_deleted', dashboardStore.invalidate)
    off('plant_care_task_created', plantsStore.handleCareTaskCreated)
    off('plant_care_task_updated', plantsStore.handleCareTaskUpdated)
    off('plant_care_task_deleted', plantsStore.handleCareTaskDeleted)
    off('plant_care_task_created', dashboardStore.invalidate)
    off('plant_care_task_updated', dashboardStore.invalidate)
    off('plant_care_task_deleted', dashboardStore.invalidate)
    off('plant_care_logged', dashboardStore.invalidate)
    off('plant_created', dashboardStore.invalidate)
    off('plant_deleted', dashboardStore.invalidate)
    BADGE_EVENTS.forEach((event) => off(event, refreshAppBadgeSoon))

    // Wenn Token weg (Logout): Socket disconnecten, Zahl am App-Icon entfernen
    if (!token) {
      disconnect()
      setAppBadgeHousehold(null)
      return
    }

    // Erstverbindung oder neues Token nach Refresh (Server verlängert die Verbindung per reauth)
    updateToken(token)

    // Alten Room verlassen
    if (oldHouseholdId && oldHouseholdId !== householdId) {
      leaveHousehold(oldHouseholdId)
    }

    if (householdId) {
      // Stores leeren bei Household-Wechsel (alle haushaltsbezogenen Stores, auch die
      // der Ansichten, die ihre Daten nur beim Öffnen laden)
      if (oldHouseholdId && oldHouseholdId !== householdId) {
        resetHouseholdScopedStores()
      }

      joinHousehold(householdId)

      // Neue Listener binden
      on('shopping_item_created', shoppingStore.handleItemCreated)
      on('shopping_item_updated', shoppingStore.handleItemUpdated)
      on('shopping_item_deleted', shoppingStore.handleItemDeleted)
      on('shopping_list_created', shoppingStore.handleListCreated)
      on('shopping_list_updated', shoppingStore.handleListUpdated)
      on('shopping_list_deleted', shoppingStore.handleListDeleted)
      on('shopping_items_bulk_updated', shoppingStore.handleBulkUpdated)
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
      on('budget_updated', financeStore.handleBudgetUpdated)
      on('budget_deleted', financeStore.handleBudgetDeleted)
      on('recurring_bill_created', financeStore.handleBillCreated)
      on('recurring_bill_updated', financeStore.handleBillUpdated)
      on('recurring_bill_deleted', financeStore.handleBillDeleted)
      on('recurring_bill_booked', financeStore.handleBillBooked)
      on('household_updated', authStore.handleHouseholdUpdated)
      on('household_member_joined', authStore.handleMemberJoined)
      on('household_member_left', authStore.handleMemberLeft)
      on('household_member_removed', authStore.handleMemberRemoved)

      // Dashboard invalidieren bei relevanten Events
      on('budget_updated', dashboardStore.invalidate)
      on('budget_deleted', dashboardStore.invalidate)
      on('recurring_bill_booked', dashboardStore.invalidate)
      on('todo_created', dashboardStore.invalidate)
      on('todo_updated', dashboardStore.invalidate)
      on('todo_deleted', dashboardStore.invalidate)
      on('shopping_item_created', dashboardStore.invalidate)
      on('shopping_item_updated', dashboardStore.invalidate)
      on('shopping_item_deleted', dashboardStore.invalidate)
      on('shopping_list_created', dashboardStore.invalidate)
      on('shopping_list_deleted', dashboardStore.invalidate)
      on('shopping_items_bulk_updated', dashboardStore.invalidate)
      on('expense_created', dashboardStore.invalidate)
      on('expense_updated', dashboardStore.invalidate)
      on('expense_deleted', dashboardStore.invalidate)
      on('settlement_created', dashboardStore.invalidate)
      on('settlement_deleted', dashboardStore.invalidate)
      on('chore_assignment_created', dashboardStore.invalidate)
      on('chore_assignment_updated', dashboardStore.invalidate)
      on('event_created', dashboardStore.invalidate)
      on('event_updated', dashboardStore.invalidate)
      on('event_deleted', dashboardStore.invalidate)
      on('poll_created', pollsStore.handleSocketCreated)
      on('poll_voted', pollsStore.handleSocketVoted)
      on('poll_decided', pollsStore.handleSocketDecided)
      on('poll_deleted', pollsStore.handleSocketDeleted)
      on('poll_decided', dashboardStore.invalidate)
      on('pet_care_task_created', petsStore.handleCareTaskCreated)
      on('pet_care_task_updated', petsStore.handleCareTaskUpdated)
      on('pet_care_task_deleted', petsStore.handleCareTaskDeleted)
      on('pet_care_task_created', dashboardStore.invalidate)
      on('pet_care_task_updated', dashboardStore.invalidate)
      on('pet_care_task_deleted', dashboardStore.invalidate)
      on('plant_care_task_created', plantsStore.handleCareTaskCreated)
      on('plant_care_task_updated', plantsStore.handleCareTaskUpdated)
      on('plant_care_task_deleted', plantsStore.handleCareTaskDeleted)
      on('plant_care_task_created', dashboardStore.invalidate)
      on('plant_care_task_updated', dashboardStore.invalidate)
      on('plant_care_task_deleted', dashboardStore.invalidate)
      on('plant_care_logged', dashboardStore.invalidate)
      on('plant_created', dashboardStore.invalidate)
      on('plant_deleted', dashboardStore.invalidate)

      // Zahl am App-Icon aktuell halten
      BADGE_EVENTS.forEach((event) => on(event, refreshAppBadgeSoon))
      setAppBadgeHousehold(householdId)

      refreshAllStores()
    }
  },
  { immediate: true }
)

// Hintergrund-Aktualisierung aller Stores. Fehler werden hier bewusst
// verschluckt: die Ansichten zeigen ihren eigenen Fehlerzustand mit „Erneut versuchen“.
function refreshAllStores() {
  const quiet = (p: Promise<unknown> | void) => { if (p) p.catch(() => {}) }
  quiet(shoppingStore.fetchLists())
  quiet(shoppingStore.fetchItems())
  quiet(shoppingStore.fetchStores())
  quiet(todosStore.fetchTodos())
  quiet(expensesStore.fetchExpenses())
  quiet(expensesStore.fetchBalances())
  quiet(settlementsStore.fetchAll())
  quiet(choresStore.fetchChores())
  quiet(choresStore.fetchAssignments())
  quiet(financeStore.fetchSummary())
  quiet(financeStore.fetchBills())
  quiet(dashboardStore.fetchDashboard())
  quiet(pollsStore.fetchPolls('offen'))
}

// Reconnect-Handler: Room neu beitreten + Daten nachladen
function handleReconnect() {
  const householdId = authStore.currentHouseholdId
  if (householdId) {
    joinHousehold(householdId)
    refreshAllStores()
    void refreshAppBadge()
  }
}

onReconnect(handleReconnect)

onUnmounted(() => {
  off('shopping_item_created', shoppingStore.handleItemCreated)
  off('shopping_item_updated', shoppingStore.handleItemUpdated)
  off('shopping_item_deleted', shoppingStore.handleItemDeleted)
  off('shopping_list_created', shoppingStore.handleListCreated)
  off('shopping_list_updated', shoppingStore.handleListUpdated)
  off('shopping_list_deleted', shoppingStore.handleListDeleted)
  off('shopping_items_bulk_updated', shoppingStore.handleBulkUpdated)
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
  off('budget_updated', financeStore.handleBudgetUpdated)
  off('budget_deleted', financeStore.handleBudgetDeleted)
  off('recurring_bill_created', financeStore.handleBillCreated)
  off('recurring_bill_updated', financeStore.handleBillUpdated)
  off('recurring_bill_deleted', financeStore.handleBillDeleted)
  off('recurring_bill_booked', financeStore.handleBillBooked)
  off('household_updated', authStore.handleHouseholdUpdated)
  off('household_member_joined', authStore.handleMemberJoined)
  off('household_member_left', authStore.handleMemberLeft)
  off('household_member_removed', authStore.handleMemberRemoved)
  off('budget_updated', dashboardStore.invalidate)
  off('budget_deleted', dashboardStore.invalidate)
  off('recurring_bill_booked', dashboardStore.invalidate)
  off('todo_created', dashboardStore.invalidate)
  off('todo_updated', dashboardStore.invalidate)
  off('todo_deleted', dashboardStore.invalidate)
  off('shopping_item_created', dashboardStore.invalidate)
  off('shopping_item_updated', dashboardStore.invalidate)
  off('shopping_item_deleted', dashboardStore.invalidate)
  off('shopping_list_created', dashboardStore.invalidate)
  off('shopping_list_deleted', dashboardStore.invalidate)
  off('shopping_items_bulk_updated', dashboardStore.invalidate)
  off('expense_created', dashboardStore.invalidate)
  off('expense_updated', dashboardStore.invalidate)
  off('expense_deleted', dashboardStore.invalidate)
  off('settlement_created', dashboardStore.invalidate)
  off('settlement_deleted', dashboardStore.invalidate)
  off('chore_assignment_created', dashboardStore.invalidate)
  off('chore_assignment_updated', dashboardStore.invalidate)
  off('poll_created', pollsStore.handleSocketCreated)
 off('poll_voted', pollsStore.handleSocketVoted)
 off('poll_decided', pollsStore.handleSocketDecided)
 off('poll_deleted', pollsStore.handleSocketDeleted)
 off('poll_decided', dashboardStore.invalidate)
 off('pet_care_task_created', petsStore.handleCareTaskCreated)
 off('pet_care_task_updated', petsStore.handleCareTaskUpdated)
 off('pet_care_task_deleted', petsStore.handleCareTaskDeleted)
  off('pet_care_task_created', dashboardStore.invalidate)
  off('pet_care_task_updated', dashboardStore.invalidate)
  off('pet_care_task_deleted', dashboardStore.invalidate)
  off('plant_care_task_created', plantsStore.handleCareTaskCreated)
  off('plant_care_task_updated', plantsStore.handleCareTaskUpdated)
  off('plant_care_task_deleted', plantsStore.handleCareTaskDeleted)
  off('plant_care_task_created', dashboardStore.invalidate)
  off('plant_care_task_updated', dashboardStore.invalidate)
  off('plant_care_task_deleted', dashboardStore.invalidate)
  off('plant_care_logged', dashboardStore.invalidate)
  off('plant_created', dashboardStore.invalidate)
  off('plant_deleted', dashboardStore.invalidate)
  BADGE_EVENTS.forEach((event) => off(event, refreshAppBadgeSoon))
  offReconnect(handleReconnect)
  setTokenRefresher(null)
  disconnect()
})
</script>

<template>
  <!-- Offline-Banner -->
  <div v-if="!isOnline" class="offline-banner" role="alert">
    <PhWifiSlash :size="16" />
    {{ $t('offline.banner') }}
  </div>

  <!-- App-Shell (authentifiziert) -->
  <div v-if="authStore.isAuthenticated" class="app-shell">

    <!-- Desktop Top-Bar (≥768px sichtbar) -->
    <header class="top-bar">
      <div class="top-bar__content">
        <span class="top-bar__brand"><PhHouse :size="20" /> {{ $t('nav.brand') }}</span>
        <nav class="top-bar__nav">
          <router-link to="/dashboard" class="top-bar__link" active-class="top-bar__link--active">
            <PhHouse :size="16" /> {{ $t('nav.start') }}
          </router-link>
          <router-link to="/calendar" class="top-bar__link" active-class="top-bar__link--active">
            <PhCalendarDots :size="16" /> {{ $t('nav.calendar') }}
          </router-link>
          <router-link to="/shopping" class="top-bar__link" active-class="top-bar__link--active">
            <PhShoppingBagOpen :size="16" /> {{ $t('nav.shopping') }}
          </router-link>
          <router-link to="/todos" class="top-bar__link" active-class="top-bar__link--active">
            <PhListChecks :size="16" /> {{ $t('nav.todos') }}
          </router-link>
          <router-link to="/expenses" class="top-bar__link" active-class="top-bar__link--active">
            <PhWallet :size="16" /> {{ $t('nav.expenses') }}
          </router-link>
          <router-link to="/household" class="top-bar__link" active-class="top-bar__link--active">
            <PhHouse :size="16" /> {{ $t('nav.household') }}
          </router-link>
          <!-- Weitere Module (Haustiere, Pflanzen, Essen, …) wie im Mobile-„Mehr“-Sheet -->
          <button
            type="button"
            class="top-bar__link top-bar__more"
            :class="{ 'top-bar__link--active': moreOpen }"
            aria-haspopup="dialog"
            :aria-expanded="moreOpen"
            @click="moreOpen = !moreOpen"
          >
            <PhDotsThreeCircle :size="16" /> {{ $t('nav.more') }}
          </button>
        </nav>
        <div class="top-bar__right">
          <!-- Household-Wechsel (nur bei >1 Haushalt) -->
          <select
            v-if="authStore.households.length > 1"
            :value="authStore.currentHouseholdId"
            @change="authStore.switchHousehold(($event.target as HTMLSelectElement).value)"
            class="household-select"
            :aria-label="$t('household.title')"
          >
            <option v-for="h in authStore.households" :key="h.id" :value="h.id">
              {{ h.name }}
            </option>
          </select>
          <BaseAvatar
            v-if="authStore.user"
            :name="authStore.user.display_name"
            :user-id="authStore.user.id"
            size="md"
          />
          <button class="top-bar__logout" @click="requestLogout">{{ $t('auth.logout') }}</button>
          <span
            class="sync-dot"
            :class="`sync-dot--${syncStatus}`"
            :title="$t(`sync.${syncStatus}`)"
            :aria-label="$t(`sync.${syncStatus}`)"
            role="status"
          />
        </div>
      </div>
    </header>

    <!-- Hauptinhalt -->
    <main class="app-content">
      <router-view />
    </main>

    <!-- Mobile Bottom-Nav + More-Sheet -->
    <TheBottomNav
      :sync-status="syncStatus"
      :more-active="moreActive"
      @toggle-more="moreOpen = !moreOpen"
    />
    <MoreSheet :open="moreOpen" @close="moreOpen = false" />

    <BaseDialog
      :open="logoutDialogOpen"
      :title="$t('auth.logoutOfflineTitle')"
      danger
      @close="logoutDialogOpen = false"
    >
      <p>{{ $t('auth.logoutOfflineConfirm') }}</p>
      <template #footer>
        <BaseButton variant="ghost" size="sm" @click="logoutDialogOpen = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton variant="danger" size="sm" @click="confirmLogout">
          {{ $t('auth.logout') }}
        </BaseButton>
      </template>
    </BaseDialog>
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
          :role="toast.type === 'error' ? 'alert' : 'status'"
        >
          <PhCheckCircle v-if="toast.type === 'success'" :size="16" />
          <PhWarningCircle v-if="toast.type === 'error'" :size="16" />
          <PhInfo v-if="toast.type === 'info'" :size="16" />
          <span class="toast__text">{{ toast.text }}</span>
          <button
            v-if="toast.action"
            class="toast__action"
            @click="toast.action.onAction(); dismissToast(toast.id)"
          >
            {{ toast.action.label }}
          </button>
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
  z-index: var(--z-banner);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background-color: var(--color-warning);
  color: var(--color-on-warning);
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
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: var(--z-nav);
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
  background: var(--chip);
  color: var(--color-text);
}

.top-bar__link--active {
  background: var(--acc-soft);
  color: var(--acc);
}

.top-bar__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}


.top-bar__more {
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
}

.top-bar__logout {
  padding: var(--space-1) var(--space-3);
  background: none;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: background var(--transition-fast);
}

.top-bar__logout:hover {
  background: var(--chip);
}

.household-select {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
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
  /* Bottom-Nav wächst um den Safe-Area-Inset → Inhalt muss mitwachsen */
  padding-bottom: calc(var(--space-4) + var(--bottom-nav-height) + var(--safe-bottom));
}

@media (min-width: 768px) {
  .app-content {
    padding-bottom: var(--space-4);
  }
}

/* ── Sync-Indikator ── */
.sync-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.sync-dot--connected {
  background-color: var(--color-success);
}

.sync-dot--reconnecting {
  background-color: var(--color-warning);
  animation: sync-pulse var(--duration-pulse) ease-in-out infinite;
}

.sync-dot--offline {
  background-color: var(--sub);
}

@keyframes sync-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* ── Toast-Container ── */
.toast-container {
  position: fixed;
  bottom: calc(var(--bottom-nav-height) + var(--safe-bottom) + var(--space-3));
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-toast);
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
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  line-height: var(--line-height-normal);
  box-shadow: var(--shadow-overlay);
  pointer-events: auto;
}

.toast__text {
  flex: 1;
}

.toast__action {
  background: none;
  border: none;
  color: inherit;
  font-weight: var(--font-weight-bold);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  white-space: nowrap;
  text-decoration: underline;
  opacity: 0.9;
  pointer-events: auto;
}

.toast__action:hover {
  opacity: 1;
}

.toast--error {
  background-color: var(--color-danger);
  color: var(--color-on-danger);
}

.toast--success {
  background-color: var(--color-success);
  color: var(--color-on-success);
}

.toast--info {
  background-color: var(--color-primary);
  color: var(--color-on-primary);
}

/* ── Toast-Transitions ── */
.toast-enter-active {
  transition: opacity var(--duration-slow) var(--ease-out), transform var(--duration-slow) var(--ease-out);
}

.toast-leave-active {
  transition: opacity var(--duration-normal) var(--ease-in), transform var(--duration-normal) var(--ease-in);
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
  transition: transform var(--transition-normal);
}
</style>
