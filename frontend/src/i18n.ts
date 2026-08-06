import { createI18n } from 'vue-i18n'
import de from './locales/de.json'
import en from './locales/en.json'

function detectLocale(): string {
  // 1. localStorage
  const stored = localStorage.getItem('haushalt_locale')
  if (stored === 'de' || stored === 'en') return stored

  // 2. navigator.language
  const nav = navigator.language || ''
  if (nav.startsWith('de')) return 'de'

  // 3. Fallback
  return 'en'
}

const i18n = createI18n({
  legacy: false, // Composition API
  locale: detectLocale(),
  fallbackLocale: 'de',
  messages: { de, en },
})

export default i18n
