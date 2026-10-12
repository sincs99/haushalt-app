/**
 * Audit (frontend_realtime_ux): Haushaltswechsel/Logout-Rennen in nicht generation-geschützten Stores.
 */
import { createPinia, setActivePinia } from 'pinia'

const FE = '/home/user/haushalt-app/frontend/src'
const { auth, shoppingRepo, todosRepo, expensesRepo, choresRepo } = vi.hoisted(() => ({
  auth: { currentHouseholdId: 'A' as string | null, user: { id: 'u1' } as any },
  shoppingRepo: { fetchAll: vi.fn(), remove: vi.fn(), update: vi.fn(), create: vi.fn() },
  todosRepo: { fetchAll: vi.fn() },
  expensesRepo: { fetchAll: vi.fn(), getBalances: vi.fn() },
  choresRepo: { fetchAssignments: vi.fn(), completeAssignment: vi.fn() },
}))
vi.mock('/home/user/haushalt-app/frontend/src/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  API_BASE: '', authRequestConfig: () => ({}),
}))
vi.mock('/home/user/haushalt-app/frontend/src/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/shoppingRepository', () => ({ createOnlineShoppingRepository: () => shoppingRepo }))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/todosRepository', () => ({ createOnlineTodosRepository: () => todosRepo }))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/expensesRepository', () => ({ createOnlineExpensesRepository: () => expensesRepo }))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/choresRepository', () => ({ createOnlineChoresRepository: () => choresRepo }))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/householdsRepository', () => ({ createOnlineHouseholdsRepository: () => ({ fetchMembers: vi.fn() }) }))

const { useShoppingStore } = await import(FE + '/stores/shopping')
const { useExpensesStore } = await import(FE + '/stores/expenses')
const { useChoresStore } = await import(FE + '/stores/chores')
const { resetHouseholdScopedStores } = await import(FE + '/stores/householdScope')

function deferred<T>() { let resolve!: (v: T) => void, reject!: (e: any) => void; const promise = new Promise<T>((r, j) => { resolve = r; reject = j }); return { promise, resolve, reject } }

beforeEach(() => { setActivePinia(createPinia()); auth.currentHouseholdId = 'A'; vi.clearAllMocks() })

test('R1 shopping.fetchItems: late response of household A lands after switch to B', async () => {
  const s = useShoppingStore()
  const a = deferred<any[]>(); const b = deferred<any[]>()
  shoppingRepo.fetchAll.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
  const pA = s.fetchItems()
  // Switch A -> B (App.vue: resetHouseholdScopedStores + refreshAllStores)
  auth.currentHouseholdId = 'B'; resetHouseholdScopedStores()
  const pB = s.fetchItems()
  b.resolve([{ id: 'b1', household_id: 'B', name: 'Brot B', version: 1 }])
  await pB
  a.resolve([{ id: 'a1', household_id: 'A', name: 'Milch A (fremder Haushalt)', version: 1 }])
  await pA
  console.log('R1 items after switch:', JSON.stringify(s.items.map((i: any) => i.household_id + ':' + i.name)))
  expect(s.items.every((i: any) => i.household_id === 'B')).toBe(false) // demonstrates leak
})

test('R2 expenses.fetchBalances: late balances of A shown in B (money)', async () => {
  const e = useExpensesStore()
  const a = deferred<any>(); const b = deferred<any>()
  expensesRepo.getBalances.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
  const pA = e.fetchBalances()
  auth.currentHouseholdId = 'B'; resetHouseholdScopedStores()
  const pB = e.fetchBalances()
  b.resolve({ household: 'B', balances: [] }); await pB
  a.resolve({ household: 'A', balances: [{ user_id: 'x', saldo_rappen: -5000 }] }); await pA
  console.log('R2 balances after switch:', JSON.stringify(e.balances))
  expect((e.balances as any).household).toBe('A')
})

test('R3 logout then login of other user: stores are NOT reset (oldHouseholdId=null path)', async () => {
  // Simulates App.vue watch: reset only when oldHouseholdId && oldHouseholdId !== householdId
  const s = useShoppingStore()
  s.items = [{ id: 'a1', household_id: 'A', name: 'Privat A', version: 1 } as any]
  const oldHouseholdId: string | null = null // after _clearState() currentHouseholdId = null
  const newHouseholdId = 'C'
  if (oldHouseholdId && oldHouseholdId !== newHouseholdId) resetHouseholdScopedStores()
  console.log('R3 items visible to next user before fetch returns:', JSON.stringify(s.items.map((i: any) => i.name)))
  expect(s.items.length).toBe(1)
})

test('R4 deleteItem: concurrent remote delete -> own DELETE 404 -> rollback resurrects ghost item', async () => {
  const s = useShoppingStore()
  s.items = [{ id: 'i1', household_id: 'A', list_id: 'l1', name: 'Milch', version: 1 } as any]
  const d = deferred<void>()
  shoppingRepo.remove.mockReturnValueOnce(d.promise)
  const p = s.deleteItem('i1')
  s.handleItemDeleted({ id: 'i1' }) // other member deleted it, socket event arrives
  d.reject(Object.assign(new Error('404'), { response: { status: 404 } }))
  await expect(p).rejects.toThrow()
  console.log('R4 items after own 404:', JSON.stringify(s.items.map((i: any) => i.id)))
  expect(s.items.map((i: any) => i.id)).toEqual(['i1'])
})

test('R5 chore schedule change by other member: assignments deleted server-side stay in UI (no event)', async () => {
  const c = useChoresStore()
  c.assignments = [{ id: 'as-old', chore_id: 'ch1', due_date: '2026-10-12', version: 1 } as any]
  // Other member PATCHes schedule -> server deletes as-old, emits only chore_updated
  c.handleChoreUpdated({ id: 'ch1', title: 'Bad', recurrence: 'weekly', weekday: 3 } as any)
  // Editing client's fetchAssignments materializes new one -> chore_assignment_created
  c.handleAssignmentCreated({ id: 'as-new', chore_id: 'ch1', due_date: '2026-10-15', version: 1 } as any)
  console.log('R5 assignments on other client:', JSON.stringify(c.assignments.map((a: any) => a.id + '@' + a.due_date)))
  expect(c.assignments.length).toBe(2)
})

test('R6 expense_updated arriving after expense_deleted resurrects deleted expense', () => {
  const e = useExpensesStore()
  e.expenses = [{ id: 'x1', description: 'Coop', amount_rappen: 1000 } as any]
  e.handleExpenseDeleted({ id: 'x1' })
  e.handleExpenseUpdated({ id: 'x1', description: 'Coop (late update)', amount_rappen: 1200 } as any)
  console.log('R6 expenses:', JSON.stringify(e.expenses.map((x: any) => x.id)))
  expect(e.expenses.length).toBe(1)
})

test('R7 refreshAllStores (token refresh/reconnect) GET snapshot older than own create wipes the item', async () => {
  const s = useShoppingStore()
  s.activeListId = 'l1'
  const get = deferred<any[]>(); const post = deferred<any>()
  shoppingRepo.fetchAll.mockReturnValueOnce(get.promise)
  shoppingRepo.create.mockImplementationOnce((_h: string, p: any) => post.promise.then(() => ({ id: p.id, household_id: 'A', list_id: 'l1', name: p.name, version: 1 })))
  const pGet = s.fetchItems()          // started by watch on token change (snapshot read before commit)
  const pAdd = s.addItem('Milch')
  post.resolve(undefined); await pAdd
  s.handleItemCreated({ id: s.items[0].id, household_id: 'A', list_id: 'l1', name: 'Milch', version: 1 } as any) // socket echo
  get.resolve([])                      // stale snapshot arrives last
  await pGet
  console.log('R7 items after stale snapshot:', JSON.stringify(s.items))
  expect(s.items.length).toBe(0)
})

test('R8 meal_plan_updated from poll decide carries only {date}', async () => {
  const { useFoodStore } = await import(FE + '/stores/food')
  const f = useFoodStore()
  f.weekPlan = [{ id: 'm1', date: '2026-10-12', recipe_id: 'r1', free_text: null, recipe: { id: 'r1', name: 'Risotto' } } as any]
  f.handleMealPlanUpdated({ date: '2026-10-12' } as any)
  console.log('R8 weekPlan entry after poll decide event:', JSON.stringify(f.weekPlan))
  expect((f.weekPlan[0] as any).recipe).toBeUndefined()
})

test('R9 addItem: server committed, socket echo arrived, REST response lost -> rollback removes confirmed item; retry uses NEW id', async () => {
  const s = useShoppingStore()
  s.activeListId = 'l1'
  const ids: string[] = []
  shoppingRepo.create.mockImplementation((_h: string, p: any) => { ids.push(p.id); return Promise.reject(Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })) })
  const p = s.addItem('Milch')
  s.handleItemCreated({ id: ids[0], household_id: 'A', list_id: 'l1', name: 'Milch', version: 1 } as any)
  await expect(p).rejects.toThrow()
  console.log('R9 items after rollback:', JSON.stringify(s.items.map((i: any) => i.id)))
  await expect(s.addItem('Milch')).rejects.toThrow()
  console.log('R9 client ids used for the two attempts:', ids[0] === ids[1] ? 'SAME' : 'DIFFERENT')
  expect(s.items.length).toBe(0)
  expect(ids[0]).not.toBe(ids[1])
})
