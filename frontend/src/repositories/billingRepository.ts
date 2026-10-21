import api from '../api/client'
import type { BillingStatus } from '../types'

/** Tarif und Abrechnung eines Haushalts (backend/app/routers/billing.py). */
export interface BillingRepository {
  fetchStatus(householdId: string): Promise<BillingStatus>
  /** Startet den Stripe-Checkout; liefert die URL, zu der der Browser wechselt. */
  startCheckout(householdId: string, interval: 'month' | 'year'): Promise<string>
  /** Öffnet das Stripe-Kundenportal (kündigen, Zahlungsmittel, Rechnungen). */
  openPortal(householdId: string): Promise<string>
}

export function createOnlineBillingRepository(): BillingRepository {
  return {
    async fetchStatus(householdId) {
      const { data } = await api.get<BillingStatus>(`/api/households/${householdId}/billing`)
      return data
    },
    async startCheckout(householdId, interval) {
      const { data } = await api.post<{ url: string }>(`/api/households/${householdId}/billing/checkout`, { interval })
      return data.url
    },
    async openPortal(householdId) {
      const { data } = await api.post<{ url: string }>(`/api/households/${householdId}/billing/portal`)
      return data.url
    },
  }
}

export const billingRepository: BillingRepository = createOnlineBillingRepository()
