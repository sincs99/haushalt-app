/**
 * Gemeinsame Test-Helfer für die Store-Tests.
 *
 * Keine *.test.ts-Datei → wird von Vitest nicht als Suite ausgeführt.
 */
import type {} from 'vitest'

/** Minimaler In-Memory-Ersatz für localStorage (Vitest läuft mit environment 'node'). */
export function createMemoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => {
      data.delete(key)
    },
    setItem: (key: string, value: string) => {
      data.set(key, String(value))
    },
  }
}

/** Promise, das von aussen aufgelöst/abgelehnt wird — für "Request in Flight"-Szenarien. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** Mock-State für useAuthStore — von den abhängigen Stores nur gelesen. */
export interface AuthMockState {
  currentHouseholdId: string | null
  user: { id: string } | null
}

export const HOUSEHOLD_ID = 'hh-1'
export const USER_ID = 'user-1'
