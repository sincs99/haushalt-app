import { createPinia, setActivePinia } from 'pinia'
const { repo, auth } = vi.hoisted(() => ({
  repo: { fetchRecipes: vi.fn(), createRecipe: vi.fn(), updateRecipe: vi.fn(), deleteRecipe: vi.fn(),
    fetchWeekPlan: vi.fn(), assignMeal: vi.fn(), removeMeal: vi.fn(), addMissingToShopping: vi.fn() },
  auth: { currentHouseholdId: 'h1' as string | null },
}))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/foodRepository', () => ({ createOnlineFoodRepository: () => repo }))
vi.mock('/home/user/haushalt-app/frontend/src/stores/auth', () => ({ useAuthStore: () => auth }))
import { useFoodStore } from '/home/user/haushalt-app/frontend/src/stores/food'
test('meal-decide socket payload {date} blanks the day', async () => {
  setActivePinia(createPinia())
  const store = useFoodStore()
  repo.fetchWeekPlan.mockResolvedValue([{ id: 'e1', date: '2026-10-20', recipe_id: null, free_text: 'Fondue', recipe: null }])
  await store.fetchWeekPlan('2026-10-19')
  store.handleMealPlanUpdated({ date: '2026-10-20' } as any)   // exactly what meal-decide emits
  const e = store.weekPlan.find(x => x.date === '2026-10-20') as any
  console.log('AUDIT entry after socket:', JSON.stringify(e))
  expect(e.recipe).toBeUndefined(); expect(e.free_text).toBeUndefined(); expect(e.id).toBeUndefined()
})
