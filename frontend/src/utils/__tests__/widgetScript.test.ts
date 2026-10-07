/**
 * Scriptable-Skript: Platzhalter werden ersetzt, nichts kann aus dem String ausbrechen.
 */
import type {} from 'vitest'
import { buildWidgetScript } from '../widgetScript'

test('fills base url, key and language', () => {
  const script = buildWidgetScript('https://casa.example.com/', 'hw_abc-123_XYZ', 'en')
  expect(script).toContain("const BASE_URL = 'https://casa.example.com'")
  expect(script).toContain("const WIDGET_KEY = 'hw_abc-123_XYZ'")
  expect(script).toContain("const LANG = 'en'")
  expect(script).not.toContain('__')
})

test('falls back to German for other locales', () => {
  expect(buildWidgetScript('https://x', 'hw_a', 'fr')).toContain("const LANG = 'de'")
})

test('strips quotes and backslashes', () => {
  const script = buildWidgetScript("https://x'; alert(1); '", "hw_a\\'", 'de')
  expect(script).toContain("const BASE_URL = 'https://x; alert(1); '")
  expect(script).toContain("const WIDGET_KEY = 'hw_a'")
})
