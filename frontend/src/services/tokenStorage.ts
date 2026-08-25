/**
 * Token-Persistence-Abstraktion.
 * Aktuelle Implementierung: localStorage (synchron, als Promise gewrapped).
 * TODO: Für native Builds (Capacitor) durch SecureStorage ersetzen.
 */

export interface Tokens {
  accessToken: string
  refreshToken: string
  /** Unix-Timestamp (ms) wann der Access-Token abläuft */
  accessExpiresAt: number
}

export interface TokenStorage {
  get(): Promise<Tokens | null>
  set(tokens: Tokens): Promise<void>
  clear(): Promise<void>
}

const STORAGE_KEY = 'haushalt_tokens'

/** Exportiert für Cross-Tab storage event Listener */
export const TOKEN_STORAGE_KEY = STORAGE_KEY

class LocalStorageTokenStorage implements TokenStorage {
  async get(): Promise<Tokens | null> {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw)
      if (parsed.accessToken && parsed.refreshToken && parsed.accessExpiresAt) {
        return parsed as Tokens
      }
      return null
    } catch {
      return null
    }
  }

  async set(tokens: Tokens): Promise<void> {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens))
  }

  async clear(): Promise<void> {
    localStorage.removeItem(STORAGE_KEY)
  }
}

export const tokenStorage: TokenStorage = new LocalStorageTokenStorage()
