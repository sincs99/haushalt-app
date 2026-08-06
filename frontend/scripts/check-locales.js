#!/usr/bin/env node
/**
 * Vergleicht die Key-Mengen von de.json und en.json.
 * Exit 1 bei Differenz.
 */
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const de = JSON.parse(readFileSync(resolve(__dirname, '../src/locales/de.json'), 'utf-8'))
const en = JSON.parse(readFileSync(resolve(__dirname, '../src/locales/en.json'), 'utf-8'))

function flatKeys(obj, prefix = '') {
  return Object.entries(obj).flatMap(([k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k
    return typeof v === 'object' && v !== null ? flatKeys(v, key) : [key]
  })
}

const deKeys = new Set(flatKeys(de))
const enKeys = new Set(flatKeys(en))

const missingInEn = [...deKeys].filter(k => !enKeys.has(k))
const missingInDe = [...enKeys].filter(k => !deKeys.has(k))

let hasError = false

if (missingInEn.length > 0) {
  console.error('❌ Keys in de.json but missing in en.json:')
  missingInEn.forEach(k => console.error(`  - ${k}`))
  hasError = true
}

if (missingInDe.length > 0) {
  console.error('❌ Keys in en.json but missing in de.json:')
  missingInDe.forEach(k => console.error(`  - ${k}`))
  hasError = true
}

if (hasError) {
  process.exit(1)
} else {
  console.log(`✅ Locale files in sync (${deKeys.size} keys)`)
}
