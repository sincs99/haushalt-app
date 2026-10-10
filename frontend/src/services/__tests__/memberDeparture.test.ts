/**
 * Austritt eines anderen Mitglieds: Stores der freigegebenen Bereiche laden neu (PD-H1).
 */
import type {} from 'vitest'

const { todos, shopping, chores, finance, polls, dashboard, refreshAppBadgeSoon } = vi.hoisted(() => ({
  todos: { fetchTodos: vi.fn(), fetchMembers: vi.fn() },
  shopping: { fetchItems: vi.fn() },
  chores: { fetchChores: vi.fn(), fetchAssignments: vi.fn(), fetchMembers: vi.fn() },
  finance: { fetchBills: vi.fn(), fetchSummary: vi.fn() },
  polls: { fetchPolls: vi.fn() },
  dashboard: { invalidate: vi.fn() },
  refreshAppBadgeSoon: vi.fn(),
}))

vi.mock('../../stores/todos', () => ({ useTodosStore: () => todos }))
vi.mock('../../stores/shopping', () => ({ useShoppingStore: () => shopping }))
vi.mock('../../stores/chores', () => ({ useChoresStore: () => chores }))
vi.mock('../../stores/finance', () => ({ useFinanceStore: () => finance }))
vi.mock('../../stores/polls', () => ({ usePollsStore: () => polls }))
vi.mock('../../stores/dashboard', () => ({ useDashboardStore: () => dashboard }))
vi.mock('../../composables/useAppBadge', () => ({ refreshAppBadgeSoon }))

import { refetchAfterMemberDeparture } from '../memberDeparture'

beforeEach(() => {
  vi.resetAllMocks()
  for (const fn of [todos.fetchTodos, todos.fetchMembers, shopping.fetchItems, chores.fetchChores,
    chores.fetchAssignments, chores.fetchMembers, finance.fetchBills, finance.fetchSummary, polls.fetchPolls]) {
    fn.mockResolvedValue(undefined)
  }
})

test('lädt nur die genannten Bereiche neu, Mitglieder und Dashboard immer', async () => {
  await refetchAfterMemberDeparture(['todos', 'chores'])

  expect(todos.fetchTodos).toHaveBeenCalled()
  expect(chores.fetchChores).toHaveBeenCalled()
  expect(chores.fetchAssignments).toHaveBeenCalled()
  expect(todos.fetchMembers).toHaveBeenCalled()
  expect(chores.fetchMembers).toHaveBeenCalled()
  expect(shopping.fetchItems).not.toHaveBeenCalled()
  expect(finance.fetchBills).not.toHaveBeenCalled()
  expect(polls.fetchPolls).not.toHaveBeenCalled()
  expect(dashboard.invalidate).toHaveBeenCalled()
  expect(refreshAppBadgeSoon).toHaveBeenCalled()
})

test('ohne released (älterer Server) wird alles neu geladen; Fehler bleiben still', async () => {
  shopping.fetchItems.mockRejectedValue(new Error('offline'))

  await refetchAfterMemberDeparture(undefined)

  expect(todos.fetchTodos).toHaveBeenCalled()
  expect(shopping.fetchItems).toHaveBeenCalled()
  expect(chores.fetchAssignments).toHaveBeenCalled()
  expect(finance.fetchBills).toHaveBeenCalled()
  expect(finance.fetchSummary).toHaveBeenCalled()
  expect(polls.fetchPolls).toHaveBeenCalledWith('offen')
})
