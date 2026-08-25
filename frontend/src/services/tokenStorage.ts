/**
 * Token-Persistence-Abstraktion.
 * Aktuelle Implementierung: localStorage.
 * TODO: Für native Builds (Capacitor) durch SecureStorage ersetzen.
 */

export interface Tokens {
  accessToken: string
  refreshToken: string
  /** Unix-Timestamp (ms) wann der Access-Token abläuft */
  accessExpiresAt: number
}

export interface TokenStorage {
  get(): Tokens | null
  set(tokens: Tokens): void
  clear(): void
}

const STORAGE_KEY = 'haushalt_tokens'

class LocalStorageTokenStorage implements TokenStorage {
  get(): Tokens | null {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw)
      // Minimale Validierung
      if (parsed.accessToken && parsed.refreshToken && parsed.accessExpiresAt) {
        return parsed as Tokens
      }
      return null
    } catch {
      return null
    }
  }

  set(tokens: Tokens): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens))
  }

  clear(): void {
    localStorage.removeItem(STORAGE_KEY)
  }
}

export const tokenStorage: TokenStorage = new LocalStorageTokenStorage()
