/**
 * Echtzeit-Sitzung des App-Rahmens: Socket-Verbindung, Room des aktuellen Haushalts,
 * Listener der Kern-Stores und Nachladen der Daten.
 *
 * - Token-Refresh (≤15 min) gibt nur das neue Token an den Socket (reauth) und lädt
 *   KEINE Stores neu (CASA-44): Ein veralteter Snapshot konnte sonst ein gerade
 *   angelegtes Element wieder verschwinden lassen.
 * - Nachgeladen wird nur bei Anmeldung, Haushaltswechsel und Reconnect.
 * - Die Stores leert der Auth-Store selbst bei jedem Haushaltswechsel/Logout (CASA-12).
 *
 * Aus App.vue ausgelagert, damit das Verhalten ohne Komponente testbar ist.
 */
import { watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useShoppingStore } from '../stores/shopping'
import { useTodosStore } from '../stores/todos'
import { useExpensesStore } from '../stores/expenses'
import { useSettlementsStore } from '../stores/settlements'
import { useChoresStore } from '../stores/chores'
import { useFinanceStore } from '../stores/finance'
import { useDashboardStore } from '../stores/dashboard'
import { usePollsStore } from '../stores/polls'
import { usePetsStore } from '../stores/pets'
import { usePlantsStore } from '../stores/plants'
import { useSocket } from './useSocket'
import { BADGE_EVENTS, refreshAppBadge, refreshAppBadgeSoon, setAppBadgeHousehold } from './useAppBadge'

export function useRealtimeSession(): { stop: () => void } {
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
  const { updateToken, joinHousehold, leaveHousehold, on, off, onReconnect, offReconnect, disconnect } = useSocket()

  // Socket-Listener des App-Rahmens: [Event, Handler]
  const socketBindings: Array<[string, (...args: any[]) => void]> = [
    ['shopping_item_created', shoppingStore.handleItemCreated],
    ['shopping_item_updated', shoppingStore.handleItemUpdated],
    ['shopping_item_deleted', shoppingStore.handleItemDeleted],
    ['shopping_list_created', shoppingStore.handleListCreated],
    ['shopping_list_updated', shoppingStore.handleListUpdated],
    ['shopping_list_deleted', shoppingStore.handleListDeleted],
    ['shopping_items_bulk_updated', shoppingStore.handleBulkUpdated],
    ['todo_created', todosStore.handleTodoCreated],
    ['todo_updated', todosStore.handleTodoUpdated],
    ['todo_deleted', todosStore.handleTodoDeleted],
    ['expense_created', expensesStore.handleExpenseCreated],
    ['expense_updated', expensesStore.handleExpenseUpdated],
    ['expense_deleted', expensesStore.handleExpenseDeleted],
    ['settlement_created', settlementsStore.handleSettlementCreated],
    ['settlement_deleted', settlementsStore.handleSettlementDeleted],
    ['chore_created', choresStore.handleChoreCreated],
    ['chore_updated', choresStore.handleChoreUpdated],
    ['chore_deleted', choresStore.handleChoreDeleted],
    ['chore_assignment_created', choresStore.handleAssignmentCreated],
    ['chore_assignment_updated', choresStore.handleAssignmentUpdated],
    ['budget_updated', financeStore.handleBudgetUpdated],
    ['recurring_bill_created', financeStore.handleBillCreated],
    ['recurring_bill_updated', financeStore.handleBillUpdated],
    ['recurring_bill_deleted', financeStore.handleBillDeleted],
    ['recurring_bill_booked', financeStore.handleBillBooked],
    ['household_updated', authStore.handleHouseholdUpdated],
    ['household_member_joined', authStore.handleMemberJoined],
    ['household_member_left', authStore.handleMemberLeft],
    ['household_member_removed', authStore.handleMemberRemoved],
    ['poll_created', pollsStore.handleSocketCreated],
    ['poll_voted', pollsStore.handleSocketVoted],
    ['poll_decided', pollsStore.handleSocketDecided],
    ['poll_deleted', pollsStore.handleSocketDeleted],
    ['pet_care_task_created', petsStore.handleCareTaskCreated],
    ['pet_care_task_updated', petsStore.handleCareTaskUpdated],
    ['pet_care_task_deleted', petsStore.handleCareTaskDeleted],
    ['plant_care_task_created', plantsStore.handleCareTaskCreated],
    ['plant_care_task_updated', plantsStore.handleCareTaskUpdated],
    ['plant_care_task_deleted', plantsStore.handleCareTaskDeleted],
    // Dashboard invalidieren bei relevanten Events
    ...[
      'budget_updated', 'recurring_bill_booked',
      'todo_created', 'todo_updated', 'todo_deleted',
      'shopping_item_created', 'shopping_item_updated', 'shopping_item_deleted',
      'shopping_list_created', 'shopping_list_deleted', 'shopping_items_bulk_updated',
      'expense_created', 'expense_updated', 'expense_deleted',
      'settlement_created', 'settlement_deleted',
      'chore_assignment_created', 'chore_assignment_updated',
      'event_created', 'event_updated', 'event_deleted',
      'poll_decided',
      'pet_care_task_created', 'pet_care_task_updated', 'pet_care_task_deleted',
      'plant_care_task_created', 'plant_care_task_updated', 'plant_care_task_deleted',
      'plant_care_logged', 'plant_created', 'plant_deleted',
    ].map((event): [string, () => void] => [event, dashboardStore.invalidate]),
    // Zahl am App-Icon aktuell halten
    ...BADGE_EVENTS.map((event): [string, () => void] => [event, refreshAppBadgeSoon]),
  ]

  function bindSocketListeners() {
    socketBindings.forEach(([event, handler]) => on(event, handler))
  }

  function unbindSocketListeners() {
    // Idempotent: entfernt nur, was gebunden ist
    socketBindings.forEach(([event, handler]) => off(event, handler))
  }

  // Token: nur an den Socket weitergeben (Server verlängert die Verbindung per reauth).
  // Ein reiner Token-Refresh (≤15 min) lädt KEINE Stores neu — ein veralteter Snapshot
  // konnte sonst ein gerade angelegtes Element wieder verschwinden lassen (CASA-44).
  const stopTokenWatch = watch(
    () => authStore.token,
    (token) => {
      if (token) updateToken(token)
    },
  )

  // Anmeldung (ob ein Token da ist, nicht welches) + aktueller Haushalt. Mehrere Quellen
  // statt eines Getters, der ein neues Array liefert — der würde bei jeder Token-Änderung
  // feuern, weil das Array jedes Mal ein anderes Objekt ist.
  const stopSessionWatch = watch(
    [() => !!authStore.token, () => authStore.currentHouseholdId],
    (newValue, oldValue) => {
      const [hasToken, householdId] = newValue
      const oldHouseholdId = oldValue?.[1] ?? null

      // IMMER zuerst alle Listener entfernen (idempotent)
      unbindSocketListeners()

      // Stores leert der Auth-Store selbst bei jedem Haushaltswechsel (auch von/nach null)
      // und beim Logout (resetHouseholdScopedStores, CASA-12)

      // Alten Room verlassen
      if (oldHouseholdId && oldHouseholdId !== householdId) {
        leaveHousehold(oldHouseholdId)
      }

      // Kein Token (Logout): Socket trennen, Zahl am App-Icon entfernen
      if (!hasToken) {
        disconnect()
        setAppBadgeHousehold(null)
        return
      }

      // Erstverbindung (gleiches Token → kein reauth)
      updateToken(authStore.token!)

      if (!householdId) {
        setAppBadgeHousehold(null)
        return
      }

      joinHousehold(householdId)
      bindSocketListeners()
      setAppBadgeHousehold(householdId)
      refreshAllStores()
    },
    { immediate: true },
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

  return {
    stop() {
      stopTokenWatch()
      stopSessionWatch()
      unbindSocketListeners()
      offReconnect(handleReconnect)
      disconnect()
    },
  }
}
