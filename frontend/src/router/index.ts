import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('../views/CalendarView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
    {
      path: '/register',
      name: 'Register',
      component: () => import('../views/RegisterView.vue'),
    },
    {
      path: '/no-household',
      name: 'no-household',
      component: () => import('../views/NoHouseholdView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/shopping',
      name: 'shopping',
      component: () => import('../views/ShoppingView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/todos',
      name: 'todos',
      component: () => import('../views/TodosView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/expenses',
      name: 'expenses',
      component: () => import('../views/ExpensesView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/chores',
      name: 'chores',
      component: () => import('../views/ChoresView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/pets',
      name: 'pets',
      component: () => import('../views/PetsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/pets/:id',
      name: 'pet-detail',
      component: () => import('../views/PetDetailView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/food',
      name: 'food',
      component: () => import('../views/FoodView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/notes',
      name: 'notes',
      component: () => import('../views/NotesView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/household',
      name: 'household',
      component: () => import('../views/HouseholdView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/',
      redirect: '/dashboard',
    },
  ],
})

// Navigation Guard: authReady abwarten, dann prüfen
router.beforeEach(async (to) => {
  if (to.meta.requiresAuth) {
    const { useAuthStore } = await import('../stores/auth')
    const authStore = useAuthStore()

    // IMMER auf authReady warten bevor irgendwas geprüft wird!
    await authStore.authReady

    if (!authStore.isAuthenticated) {
      // Redirect-URL merken für nach dem Login
      return { path: '/login', query: { redirect: to.fullPath } }
    }

    // Nur die "keine Haushalte"-Prüfung anwenden wenn fetchMe mindestens
    // einmal erfolgreich war (user ist gesetzt). Wenn user null ist aber
    // tokens existieren (z.B. Backend offline), durchlassen — die View
    // wird ihren eigenen Fehlerzustand zeigen.
    if (
      authStore.user !== null &&
      to.path !== '/no-household' &&
      authStore.households.length === 0
    ) {
      return { path: '/no-household' }
    }
  }
})

export default router
