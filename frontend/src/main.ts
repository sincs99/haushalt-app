import '@fontsource/nunito/latin-400.css'
import '@fontsource/nunito/latin-500.css'
import '@fontsource/nunito/latin-600.css'
import '@fontsource/nunito/latin-700.css'
import '@fontsource/quicksand/latin-500.css'
import '@fontsource/quicksand/latin-600.css'
import '@fontsource/quicksand/latin-700.css'
import './assets/theme.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { initTheme } from './composables/useTheme'
import { initPwa } from './pwa'

initTheme()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Auth initialisieren BEVOR Router aktiviert wird
// Das stellt sicher, dass authReady vor der ersten Navigation resolved wird
import { useAuthStore } from './stores/auth'
const authStore = useAuthStore()
authStore.initialize()

app.use(router)
app.use(i18n)
app.mount('#app')

initPwa()
