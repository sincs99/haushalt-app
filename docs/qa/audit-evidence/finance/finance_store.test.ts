import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from '/home/user/haushalt-app/frontend/node_modules/pinia'
vi.mock('/home/user/haushalt-app/frontend/src/stores/auth', () => ({ useAuthStore: () => ({ currentHouseholdId: 'h1' }) }))
vi.mock('/home/user/haushalt-app/frontend/src/repositories/financeRepository', () => ({ createOnlineFinanceRepository: () => ({}) }))
import { useFinanceStore } from '/home/user/haushalt-app/frontend/src/stores/finance'

describe('finance store socket merge', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it('budget_updated for ANOTHER month overwrites the displayed month summary', () => {
    const f = useFinanceStore()
    f.summary = { month: '2026-10-01', budget_rappen: 100000, total_spent_rappen: 40000, remaining_rappen: 60000,
      days_elapsed: 10, days_in_month: 31, by_category: [], pending_bills: [] } as any
    f.handleBudgetUpdated({ id: 'b2', household_id: 'h1', month: '2026-11-01', amount_rappen: 5000, created_at: '', updated_at: '' } as any)
    console.log('OBSERVED summary after Nov budget event:', f.summary!.month, f.summary!.budget_rappen, f.summary!.remaining_rappen)
    expect(f.summary!.budget_rappen).toBe(5000)   // documents the bug: October card now shows November's budget
  })
  it('recurring_bill_created/updated does not touch summary.pending_bills', () => {
    const f = useFinanceStore()
    f.summary = { month: '2026-10-01', budget_rappen: null, total_spent_rappen: 0, remaining_rappen: null, days_elapsed: 1, days_in_month: 31, by_category: [],
      pending_bills: [{ id: 'b1', name: 'Internet', amount_rappen: 6000, day_of_month: 5, category: null, is_booked_this_month: false }] } as any
    f.handleBillUpdated({ id: 'b1', name: 'Internet', amount_rappen: 9000, day_of_month: 5, active: true } as any)
    f.handleBillCreated({ id: 'b2', name: 'Strom', amount_rappen: 100, day_of_month: 1, active: true } as any)
    f.handleBillDeleted({ id: 'b1' })
    console.log('OBSERVED pending_bills:', JSON.stringify(f.summary!.pending_bills.map((b: any) => [b.id, b.amount_rappen])))
    expect(f.summary!.pending_bills.map((b: any) => b.amount_rappen)).toEqual([6000])
  })
})
