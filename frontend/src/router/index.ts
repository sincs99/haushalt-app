import { createRouter, createWebHistory } from 'vue-router'
import { waitForOverlayBack } from '../composables/useBackClose'

const router = createRouter({
  history: createWebHistory(),
  // Zurück stellt die Scroll-Position wieder her, neue Seiten starten oben
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.path === from.path) return false
    return { top: 0 }
  },
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
      path: '/plants',
      name: 'plants',
      component: () => import('../views/PlantsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/plants/:id',
      name: 'plant-detail',
      component: () => import('../views/PlantDetailView.vue'),
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
      path: '/documents',
      name: 'documents',
      component: () => import('../views/DocumentsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/AssistantView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/household',
      name: 'household',
      component: () => import('../views/HouseholdView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tags',
      name: 'tags',
      component: () => import('../views/TagsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      // Ziel der NFC-Chip-/QR-URL. Login erzwingt der Guard unten (redirect
      // zurück hierher); die Aktion selbst läuft erst nach Bestätigung.
      path: '/t/:token',
      name: 'tag-scan',
      component: () => import('../views/TagScanView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/',
      redirect: '/dashboard',
    },
    // Unbekannte Adressen (alte Links, Tippfehler) → Start statt leerer Seite
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

// Ein gerade geschlossener Dialog nimmt seinen History-Eintrag zurück –
// erst danach navigieren, sonst würde die neue Seite gleich wieder verlassen.
router.beforeEach(() => waitForOverlayBack())

// Navigation Guard: authReady abwarten, dann prüfen
router.beforeEach(async (to) => {
  // Bereits angemeldet: Login-/Registrierungsformular nicht erneut zeigen
  // (Registrierung mit Einladungscode bleibt erreichbar)
  if (to.name === 'login' || (to.name === 'Register' && !to.query.code)) {
    const { useAuthStore } = await import('../stores/auth')
    const authStore = useAuthStore()
    await authStore.authReady
    if (authStore.isAuthenticated) {
      const redirect = typeof to.query.redirect === 'string' && to.query.redirect.startsWith('/') ? to.query.redirect : '/dashboard'
      return { path: redirect }
    }
  }

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
