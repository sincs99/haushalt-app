import i18n from '../i18n'

/**
 * Übersetzt einen API-Fehler in einen lokalisierten String.
 *
 * Priorität:
 * 1. detail.code → errors.<CODE> i18n-Key
 * 2. detail.message → englischer Fallback
 * 3. error.message → generischer Fehler
 * 4. errors.unknown → letzter Fallback
 */
export function translateApiError(error: any): string {
  const t = i18n.global.t

  // Axios-Fehler mit response.data.detail
  const detail = error?.response?.data?.detail

  if (detail && typeof detail === 'object' && detail.code) {
    // Strukturierter Fehler vom Backend
    const key = `errors.${detail.code}`
    const translated = t(key)
    // Wenn der Key nicht existiert, gibt vue-i18n den Key selbst zurück
    if (translated !== key) {
      return translated
    }
    // Fallback auf message
    if (detail.message) {
      return detail.message
    }
  }

  // Legacy: detail ist ein String (Pydantic-Validierung oder alte API)
  if (detail && typeof detail === 'string') {
    return detail
  }

  // Pydantic-Validierung: detail ist ein Array
  if (detail && Array.isArray(detail)) {
    return detail.map((e: any) => e.msg || JSON.stringify(e)).join(', ')
  }

  // Netzwerk-Fehler (kein Response)
  if (error?.message && !error?.response) {
    return t('errors.network')
  }

  // Generischer Fehler
  if (error?.message) {
    return error.message
  }

  return t('errors.unknown')
}
