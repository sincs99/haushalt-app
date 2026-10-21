/**
 * Haushaltswechsel: Alle haushaltsbezogenen Stores leeren.
 *
 * Wird vom Auth-Store bei JEDEM Wechsel von currentHouseholdId aufgerufen (auch von/nach
 * `null`, z. B. letzten Haushalt verlassen und neuen anlegen) und beim Logout
 * (auth._clearState), bevor App.vue den neuen Haushalt lädt. Ohne das zeigen Ansichten, die ihre Daten nur beim Öffnen laden
 * (Haustiere, Pflanzen, Notizen, Essen), weiter die Daten des alten Haushalts — und
 * Aktionen darauf gingen gegen den neuen Haushalt (Logik-Review L-07); nach Logout +
 * Login eines anderen Users sähe dieser die Daten des Vorgängers (CASA-12).
 *
 * Erhöht ausserdem die Haushalts-Generation: Antworten von Requests, die vor dem Reset
 * gestartet wurden, werden von den Stores verworfen (utils/householdGuard.ts).
 * Der Auth-Store (Haushaltsliste, User) bleibt unberührt.
 */
import { useShoppingStore } from './shopping'
import { useTodosStore } from './todos'
import { useExpensesStore } from './expenses'
import { useSettlementsStore } from './settlements'
import { useChoresStore } from './chores'
import { useFinanceStore } from './finance'
import { useDashboardStore } from './dashboard'
import { usePollsStore } from './polls'
import { useCalendarStore } from './calendar'
import { usePetsStore } from './pets'
import { usePlantsStore } from './plants'
import { useNotesStore } from './notes'
import { useFoodStore } from './food'
import { useAiStore } from './ai'
import { useDocumentsStore } from './documents'
import { useTagsStore } from './tags'
import { bumpHouseholdGeneration } from '../utils/householdGuard'
import { clearToasts } from '../composables/useToast'

export function resetHouseholdScopedStores(): void {
  bumpHouseholdGeneration()
  clearToasts()

  const shopping = useShoppingStore()
  shopping.resetPending()
  shopping.items = []
  shopping.lists = []
  shopping.activeListId = null
  shopping.stores = []
  shopping.activeStoreFilter = null
  shopping.loading = false

  const todos = useTodosStore()
  todos.resetPending()
  todos.items = []
  todos.members = []
  todos.loading = false

  const expenses = useExpensesStore()
  expenses.expenses = []
  expenses.balances = null
  expenses.members = []
  expenses.hasMore = false
  expenses.deletedExpenses = []
  expenses.deletedLoaded = false
  expenses.loading = false
  expenses.error = null
  expenses.balancesError = false
  expenses.loadingMore = false

  const settlements = useSettlementsStore()
  settlements.settlements = []
  settlements.hasMore = false
  settlements.deletedSettlements = []
  settlements.deletedLoaded = false
  settlements.loading = false
  settlements.error = null
  settlements.loadingMore = false

  const chores = useChoresStore()
  chores.resetPending()
  chores.chores = []
  chores.assignments = []
  chores.members = []
  chores.loading = false

  const finance = useFinanceStore()
  finance.budget = null
  finance.bills = []
  finance.summary = null
  finance.loading = false
  finance.error = null

  useDashboardStore().data = null
  useDashboardStore().loadError = false
  useDashboardStore().loading = false
  usePollsStore().polls = []
  usePollsStore().loading = false

  useCalendarStore().reset()
  usePetsStore().reset()
  usePlantsStore().reset()
  useNotesStore().reset()
  useFoodStore().reset()
  useAiStore().reset()
  useDocumentsStore().reset()
  useTagsStore().$reset()
}
