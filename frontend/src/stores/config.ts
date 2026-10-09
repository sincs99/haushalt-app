import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api/client'

/** Öffentliche Server-Konfiguration (GET /api/config): Schalter zum Ein-/Ausblenden von Funktionen. */
export interface PublicConfig {
  mail_enabled: boolean
  /** Tarife aktiv (SaaS-Betrieb) → Tarif-Karte in den Einstellungen */
  billing_enabled: boolean
  /** Stripe eingerichtet → Upgrade im Web möglich */
  checkout_available: boolean
  /** Registrierung verlangt Zustimmung zu AGB/Datenschutz */
  terms_required: boolean
  terms_version: string
  /** Betreiberangaben für Impressum/Datenschutz */
  operator: { name: string; address_lines: string[]; email: string }
}

const DEFAULTS: PublicConfig = {
  mail_enabled: false,
  billing_enabled: false,
  checkout_available: false,
  terms_required: false,
  terms_version: '',
  operator: { name: '', address_lines: [], email: '' },
}

export const useConfigStore = defineStore('config', () => {
  const config = ref<PublicConfig>({ ...DEFAULTS })
  const loaded = ref(false)
  let _pending: Promise<void> | null = null

  /** Lädt die Konfiguration einmal; Fehler (offline) lassen die Standardwerte stehen. */
  async function load(): Promise<void> {
    if (loaded.value) return
    if (_pending) return _pending
    _pending = (async () => {
      try {
        const { data } = await api.get<PublicConfig>('/api/config')
        config.value = { ...DEFAULTS, ...data }
        loaded.value = true
      } catch {
        // Offline oder altes Backend: Standardwerte (alles ausgeblendet)
      } finally {
        _pending = null
      }
    })()
    return _pending
  }

  return { config, loaded, load }
})
