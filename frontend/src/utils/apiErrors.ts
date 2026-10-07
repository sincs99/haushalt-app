import i18n from '../i18n'

/**
 * Übersetzt einen API-Fehler in einen lokalisierten String.
 *
 * Priorität:
 * 1. detail.code → errors.<CODE> i18n-Key
 * 2. detail.message (unbekannter Code)
 * 3. kein Response → errors.network
 * 4. nach HTTP-Status: 404 → errors.notFound, 400/422 → errors.validation, 5xx → errors.server
 * 5. errors.unknown
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

  // Netzwerk-Fehler (kein Response)
  if (error?.message && !error?.response) {
    return t('errors.network')
  }

  // Alles Weitere (Text-Details aus älteren Endpunkten, Pydantic-Arrays, leere
  // Antworten) ist englisch oder technisch – nie roh anzeigen, sondern nach Status.
  const status: number | undefined = error?.response?.status
  if (status === 404) return t('errors.notFound')
  if (status === 400 || status === 422 || Array.isArray(detail)) return t('errors.validation')
  if (status !== undefined && status >= 500) return t('errors.server')

  return t('errors.unknown')
}
