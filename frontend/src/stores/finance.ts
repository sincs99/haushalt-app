import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineFinanceRepository } from '../repositories/financeRepository'
import { translateApiError } from '../utils/apiErrors'
import type { Budget, RecurringBill, FinanceSummary, RecurringBillCreatePayload, RecurringBillUpdatePayload, BudgetUpsertPayload, Expense } from '../types'

export const useFinanceStore = defineStore('finance', () => {
  const repo = scopeRepository(createOnlineFinanceRepository())

  // State
  const budget = ref<Budget | null>(null)
  const bills = ref<RecurringBill[]>([])
  const summary = ref<FinanceSummary | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Actions
  async function fetchSummary(householdId?: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    loading.value = true
    error.value = null
    try {
      const scopedResult = await repo.getSummary(hid)
      assertDataGeneration(actionGeneration)
      summary.value = scopedResult
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      // Weiterwerfen, damit die Ansicht einen Fehlerzustand zeigen kann
      throw e
    } finally {
      assertDataGeneration(actionGeneration)
      loading.value = false
    }
  }

  async function fetchBudget(householdId?: string, month?: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    try {
      const scopedResult = await repo.getBudget(hid, month)
      assertDataGeneration(actionGeneration)
      budget.value = scopedResult
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      console.error('Failed to fetch budget:', e)
    }
  }

  async function upsertBudget(payload: BudgetUpsertPayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const scopedResult = await repo.upsertBudget(hid, payload)
      assertDataGeneration(actionGeneration)
      budget.value = scopedResult
      // Summary nachladen (Rest etc.) — scheitert das, ist das Budget trotzdem gespeichert
      await fetchSummary(hid).catch(() => {})
      assertDataGeneration(actionGeneration)
      return budget.value
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  async function fetchBills(householdId?: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    try {
      const scopedResult = await repo.fetchBills(hid)
      assertDataGeneration(actionGeneration)
      bills.value = scopedResult
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      console.error('Failed to fetch bills:', e)
    }
  }

  async function createBill(payload: RecurringBillCreatePayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const created = await repo.createBill(hid, payload)
      assertDataGeneration(actionGeneration)
      bills.value.push(created)
      return created
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  async function updateBill(billId: string, payload: RecurringBillUpdatePayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const updated = await repo.updateBill(hid, billId, payload)
      assertDataGeneration(actionGeneration)
      const idx = bills.value.findIndex(b => b.id === billId)
      if (idx !== -1) bills.value[idx] = updated
      return updated
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  async function removeBill(billId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    try {
      await repo.removeBill(hid, billId)
      assertDataGeneration(actionGeneration)
      bills.value = bills.value.filter(b => b.id !== billId)
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  async function bookBill(billId: string, paidByUserId?: string): Promise<Expense | undefined> {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const expense = await repo.bookBill(hid, billId, paidByUserId)
      // Summary nachladen (pending_bills) — scheitert das, ist die Rechnung trotzdem gebucht
      assertDataGeneration(actionGeneration)
      await fetchSummary(hid).catch(() => {})
      assertDataGeneration(actionGeneration)
      return expense
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  // Socket handlers
  function handleBudgetUpdated(data: Budget) {
    budget.value = data
    // Also update summary if loaded
    if (summary.value) {
      summary.value.budget_rappen = data.amount_rappen
      if (summary.value.budget_rappen !== null) {
        summary.value.remaining_rappen = data.amount_rappen - summary.value.total_spent_rappen
      }
    }
  }

  function handleBillCreated(bill: RecurringBill) {
    const idx = bills.value.findIndex(b => b.id === bill.id)
    if (idx === -1) bills.value.push(bill)
    else bills.value[idx] = bill
  }

  function handleBillUpdated(bill: RecurringBill) {
    const idx = bills.value.findIndex(b => b.id === bill.id)
    if (idx !== -1) bills.value[idx] = bill
    else bills.value.push(bill)
  }

  function handleBillDeleted(data: { id: string }) {
    bills.value = bills.value.filter(b => b.id !== data.id)
  }

  function handleBillBooked(_data: { bill_id: string; expense_id: string }) {
    // Mark bill as booked in summary
    if (summary.value) {
      const pending = summary.value.pending_bills.find(b => b.id === _data.bill_id)
      if (pending) pending.is_booked_this_month = true
    }
  }

  return {
    // State
    budget,
    bills,
    summary,
    loading,
    error,
    // Actions
    fetchSummary,
    fetchBudget,
    upsertBudget,
    fetchBills,
    createBill,
    updateBill,
    removeBill,
    bookBill,
    // Socket handlers
    handleBudgetUpdated,
    handleBillCreated,
    handleBillUpdated,
    handleBillDeleted,
    handleBillBooked,
  }
})
