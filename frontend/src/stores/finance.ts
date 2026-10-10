import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineFinanceRepository } from '../repositories/financeRepository'
import { translateApiError } from '../utils/apiErrors'
import { createRequestGuard } from '../utils/householdGuard'
import type { Budget, RecurringBill, FinanceSummary, RecurringBillCreatePayload, RecurringBillUpdatePayload, BudgetUpsertPayload, Expense } from '../types'

export const useFinanceStore = defineStore('finance', () => {
  const repo = createOnlineFinanceRepository()

  // State
  const budget = ref<Budget | null>(null)
  const bills = ref<RecurringBill[]>([])
  const summary = ref<FinanceSummary | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()
  // Rechnungs-Events ändern pending_bills der Übersicht → gebündelt neu laden (CASA-42)
  let summaryTimer: ReturnType<typeof setTimeout> | null = null
  function debouncedFetchSummary() {
    if (summaryTimer) clearTimeout(summaryTimer)
    summaryTimer = setTimeout(() => {
      const hid = useAuthStore().currentHouseholdId
      if (hid && summary.value) fetchSummary(hid).catch(() => {})
    }, 300)
  }

  // Actions
  async function fetchSummary(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'summary')

    loading.value = true
    error.value = null
    try {
      const result = await repo.getSummary(hid)
      if (active()) summary.value = result
    } catch (e: any) {
      if (active()) error.value = translateApiError(e)
      // Weiterwerfen, damit die Ansicht einen Fehlerzustand zeigen kann
      throw e
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  async function fetchBudget(householdId?: string, month?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'budget')

    try {
      const result = await repo.getBudget(hid, month)
      if (active()) budget.value = result
    } catch (e: any) {
      console.error('Failed to fetch budget:', e)
    }
  }

  async function upsertBudget(payload: BudgetUpsertPayload) {
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      budget.value = await repo.upsertBudget(hid, payload)
      // Summary nachladen (Rest etc.) — scheitert das, ist das Budget trotzdem gespeichert
      await fetchSummary(hid).catch(() => {})
      return budget.value
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  async function fetchBills(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'bills')

    try {
      // Inklusive inaktiver Rechnungen — die Verwaltung zeigt und reaktiviert sie
      const result = await repo.fetchBills(hid, true)
      if (active()) bills.value = result
    } catch (e: any) {
      console.error('Failed to fetch bills:', e)
    }
  }

  async function createBill(payload: RecurringBillCreatePayload) {
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const created = await repo.createBill(hid, payload)
      if (!bills.value.some(b => b.id === created.id)) bills.value.push(created)
      await fetchSummary(hid).catch(() => {})
      return created
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  async function updateBill(billId: string, payload: RecurringBillUpdatePayload) {
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const updated = await repo.updateBill(hid, billId, payload)
      const idx = bills.value.findIndex(b => b.id === billId)
      if (idx !== -1) bills.value[idx] = updated
      await fetchSummary(hid).catch(() => {})
      return updated
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  async function removeBill(billId: string) {
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    try {
      await repo.removeBill(hid, billId)
      bills.value = bills.value.filter(b => b.id !== billId)
      await fetchSummary(hid).catch(() => {})
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  /** `month` (YYYY-MM-01) bucht einen vergessenen Monat nach (max. 12 Monate zurück, PD-F4) */
  async function bookBill(billId: string, paidByUserId?: string, month?: string): Promise<Expense | undefined> {
    const authStore = useAuthStore()
    const hid = authStore.currentHouseholdId
    if (!hid) return

    error.value = null
    try {
      const expense = month
        ? await repo.bookBill(hid, billId, paidByUserId, month)
        : await repo.bookBill(hid, billId, paidByUserId)
      // Summary nachladen (pending_bills) — scheitert das, ist die Rechnung trotzdem gebucht
      await fetchSummary(hid).catch(() => {})
      return expense
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  // Socket handlers
  // Budget-Events gelten nur für ihren Monat: ein Budget für einen anderen Monat darf
  // „Noch verfügbar“ des angezeigten Monats nicht überschreiben (CASA-42)
  function handleBudgetUpdated(data: Budget) {
    const shownMonth = summary.value?.month ?? budget.value?.month
    if (shownMonth && shownMonth !== data.month) return
    budget.value = data
    if (summary.value) {
      summary.value.budget_rappen = data.amount_rappen
      summary.value.remaining_rappen = data.amount_rappen - summary.value.total_spent_rappen
    }
  }

  function handleBudgetDeleted(data: { month: string }) {
    if (budget.value?.month === data.month) budget.value = null
    if (summary.value && summary.value.month === data.month) {
      summary.value.budget_rappen = null
      summary.value.remaining_rappen = null
    }
  }

  function handleBillCreated(bill: RecurringBill) {
    const idx = bills.value.findIndex(b => b.id === bill.id)
    if (idx === -1) bills.value.push(bill)
    else bills.value[idx] = bill
    debouncedFetchSummary()
  }

  function handleBillUpdated(bill: RecurringBill) {
    const idx = bills.value.findIndex(b => b.id === bill.id)
    if (idx !== -1) bills.value[idx] = bill
    else bills.value.push(bill)
    debouncedFetchSummary()
  }

  function handleBillDeleted(data: { id: string }) {
    bills.value = bills.value.filter(b => b.id !== data.id)
    debouncedFetchSummary()
  }

  function handleBillBooked(data: { bill_id: string; expense_id: string; booked_month?: string }) {
    // Nur markieren, wenn die Buchung den angezeigten Monat betrifft (Nachbuchung, PD-F4)
    if (!summary.value) return
    if (data.booked_month && data.booked_month !== summary.value.month) return
    const pending = summary.value.pending_bills.find(b => b.id === data.bill_id)
    if (pending) pending.is_booked_this_month = true
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
    handleBudgetDeleted,
    handleBillCreated,
    handleBillUpdated,
    handleBillDeleted,
    handleBillBooked,
  }
})
