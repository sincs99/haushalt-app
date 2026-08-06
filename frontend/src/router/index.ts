import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
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
      path: '/household',
      name: 'household',
      component: () => import('../views/HouseholdView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/',
      redirect: '/shopping',
    },
  ],
})

// Navigation Guard: redirect zu /login wenn kein Token
router.beforeEach(async (to) => {
  if (to.meta.requiresAuth) {
    const { useAuthStore } = await import('../stores/auth')
    const authStore = useAuthStore()
    if (!authStore.isAuthenticated) {
      return { path: '/login' }
    }
    // Authentifiziert aber keine Haushalte → NoHousehold
    // (ausser wir gehen bereits zu /no-household)
    if (to.path !== '/no-household' && authStore.households.length === 0) {
      return { path: '/no-household' }
    }
  }
})

export default router
