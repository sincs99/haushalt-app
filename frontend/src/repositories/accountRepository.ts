import api, { authRequestConfig } from '../api/client'
import type { TokenResponse } from '../types'

/** Konto-Funktionen (backend/app/routers/account.py). */
export interface AccountRepository {
  forgotPassword(email: string): Promise<void>
  resetPassword(token: string, password: string): Promise<void>
  verifyEmail(token: string): Promise<void>
  resendVerification(): Promise<void>
  /** Meldet alle anderen Geräte ab; liefert ein neues Token-Paar für dieses Gerät. */
  changePassword(currentPassword: string, newPassword: string): Promise<TokenResponse>
  deleteAccount(password: string): Promise<void>
}

export function createOnlineAccountRepository(): AccountRepository {
  return {
    async forgotPassword(email) {
      await api.post('/api/account/password/forgot', { email })
    },
    async resetPassword(token, password) {
      await api.post('/api/account/password/reset', { token, password })
    },
    async verifyEmail(token) {
      await api.post('/api/account/email/verify', { token })
    },
    async resendVerification() {
      await api.post('/api/account/email/resend')
    },
    async changePassword(currentPassword, newPassword) {
      const { data } = await api.put<TokenResponse>(
        '/api/account/password',
        { current_password: currentPassword, new_password: newPassword },
        authRequestConfig(),
      )
      return data
    },
    async deleteAccount(password) {
      await api.delete('/api/account', { data: { password } })
    },
  }
}

export const accountRepository: AccountRepository = createOnlineAccountRepository()
