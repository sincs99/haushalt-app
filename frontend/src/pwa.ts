import { registerSW } from 'virtual:pwa-register'
import i18n from './i18n'
import { useToast } from './composables/useToast'
import { setUpdateAvailable, watchForUpdates } from './composables/usePwaUpdate'

/**
 * Registriert den Service Worker. Liegt eine neue Version bereit,
 * bietet ein Toast das Neuladen an (statt automatisch neu zu laden); zusätzlich bleibt
 * „Update verfügbar“ im Mehr-Sheet stehen. Nach neuen Versionen wird beim Zurückkehren
 * in die App und stündlich gesucht (CASA-41).
 */
export function initPwa() {
  const { showToast } = useToast()
  const t = i18n.global.t

  const updateSW = registerSW({
    onNeedRefresh() {
      setUpdateAvailable(() => updateSW(true))
      showToast(t('pwa.updateAvailable'), 'info', 60_000, {
        label: t('pwa.reload'),
        onAction: () => updateSW(true),
      })
    },
    onRegisteredSW(_swUrl, registration) {
      if (registration) watchForUpdates(registration)
    },
  })
}
