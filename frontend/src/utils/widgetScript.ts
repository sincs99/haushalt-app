import template from '../assets/scriptable-widget.js?raw'

/**
 * Scriptable-Skript mit eingesetzter Adresse, Schlüssel und Sprache.
 * Die Vorlage liegt in assets/scriptable-widget.js (läuft nur in Scriptable, nicht im Browser).
 */
export function buildWidgetScript(baseUrl: string, key: string, lang: string): string {
  const safe = (value: string) => value.replace(/[\\']/g, '')
  return template
    .replace('__BASE_URL__', safe(baseUrl.replace(/\/+$/, '')))
    .replace('__WIDGET_KEY__', safe(key))
    .replace('__LANG__', lang === 'en' ? 'en' : 'de')
}
