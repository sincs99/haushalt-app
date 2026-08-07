import { ref, watch } from 'vue'

type ThemePreference = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'casa_theme'

const preference = ref<ThemePreference>(
  (localStorage.getItem(STORAGE_KEY) as ThemePreference) || 'system'
)

function applyTheme(pref: ThemePreference): void {
  let resolved: 'light' | 'dark'
  if (pref === 'system') {
    resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } else {
    resolved = pref
  }
  document.documentElement.setAttribute('data-theme', resolved)
}

// Listen to OS theme changes when set to 'system'
const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
mediaQuery.addEventListener('change', () => {
  if (preference.value === 'system') {
    applyTheme('system')
  }
})

watch(preference, (newPref) => {
  localStorage.setItem(STORAGE_KEY, newPref)
  applyTheme(newPref)
}, { immediate: true })

export function useTheme() {
  return {
    preference,
    applyTheme,
  }
}

/** Call once at app startup (before mount) to avoid flash */
export function initTheme(): void {
  applyTheme(preference.value)
}
