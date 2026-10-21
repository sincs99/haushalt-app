/** Haushaltswechsel: verspätete Antwort des alten Haushalts überschreibt den neuen Store? */
import { createPinia, setActivePinia } from 'pinia'
const { auth, pending } = vi.hoisted(() => ({
  auth: { currentHouseholdId: 'hh-A' as string | null, user: { id: 'u1' } },
  pending: new Map<string, (v: any) => void>(),
}))
vi.mock('/home/user/haushalt-app/frontend/src/api/client', () => ({
  default: {
    get: vi.fn((url: string) => new Promise((resolve) => pending.set(url, (data) => resolve({ data })))),
    post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn(),
  },
  API_BASE: '', authRequestConfig: () => ({}),
}))
vi.mock('/home/user/haushalt-app/frontend/src/stores/auth', () => ({ useAuthStore: () => auth }))
import { useTodosStore } from '/home/user/haushalt-app/frontend/src/stores/todos'
import { useShoppingStore } from '/home/user/haushalt-app/frontend/src/stores/shopping'
import { usePetsStore } from '/home/user/haushalt-app/frontend/src/stores/pets'
import { resetHouseholdScopedStores } from '/home/user/haushalt-app/frontend/src/stores/householdScope'

beforeEach(() => { setActivePinia(createPinia()); pending.clear(); auth.currentHouseholdId = 'hh-A' })

function resolveMatching(part: string, data: any) {
  for (const [url, fn] of pending) if (url.includes(part)) { fn(data); pending.delete(url); return url }
  throw new Error('no pending ' + part + ' in ' + [...pending.keys()].join(','))
}

test('todos: late response from household A lands in household B store', async () => {
  const todos = useTodosStore()
  const pA = todos.fetchTodos()                 // request for A in flight
  auth.currentHouseholdId = 'hh-B'; resetHouseholdScopedStores()
  const pB = todos.fetchTodos()                 // request for B
  resolveMatching('hh-B', [{ id: 'b1', household_id: 'hh-B', title: 'B-Todo', version: 1 }])
  await pB
  resolveMatching('hh-A', [{ id: 'a1', household_id: 'hh-A', title: 'A-Todo', version: 1 }])
  await pA
  console.log('TODOS after switch:', JSON.stringify(todos.items.map(i => i.household_id + ':' + i.title)))
  expect(todos.items.map(i => i.household_id)).toEqual(['hh-A'])   // documents the defect
})

test('pets (guarded store) keeps household B data', async () => {
  const pets = usePetsStore()
  const pA = pets.fetchPets()
  auth.currentHouseholdId = 'hh-B'; resetHouseholdScopedStores()
  const pB = pets.fetchPets()
  resolveMatching('hh-B', [{ id: 'pb', household_id: 'hh-B', name: 'B-Katze' }]); await pB
  resolveMatching('hh-A', [{ id: 'pa', household_id: 'hh-A', name: 'A-Hund' }]); await pA
  console.log('PETS after switch:', JSON.stringify(pets.pets.map((p: any) => p.household_id + ':' + p.name)))
  expect(pets.pets.map((p: any) => p.household_id)).toEqual(['hh-B'])
})

test('shopping items: late response from A', async () => {
  const s = useShoppingStore()
  const pA = s.fetchItems()
  auth.currentHouseholdId = 'hh-B'; resetHouseholdScopedStores()
  const pB = s.fetchItems()
  resolveMatching('hh-B', [{ id: 'sb', household_id: 'hh-B', name: 'Milch-B', version: 1 }]); await pB
  resolveMatching('hh-A', [{ id: 'sa', household_id: 'hh-A', name: 'Brot-A', version: 1 }]); await pA
  console.log('SHOPPING after switch:', JSON.stringify(s.items.map((i: any) => i.household_id + ':' + i.name)))
})
