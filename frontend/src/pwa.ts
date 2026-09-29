import { registerSW } from 'virtual:pwa-register'
import i18n from './i18n'
import { useToast } from './composables/useToast'

/**
 * Registriert den Service Worker. Liegt eine neue Version bereit,
 * bietet ein Toast das Neuladen an (statt automatisch neu zu laden).
 */
export function initPwa() {
  const { showToast } = useToast()
  const t = i18n.global.t

  const updateSW = registerSW({
    onNeedRefresh() {
      showToast(t('pwa.updateAvailable'), 'info', 60_000, {
        label: t('pwa.reload'),
        onAction: () => updateSW(true),
      })
    },
  })
}
