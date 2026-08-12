<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useExpensesStore } from '../stores/expenses'
import { useFinanceStore } from '../stores/finance'
import { useSettlementsStore } from '../stores/settlements'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { formatRappen, parseAmountToRappen } from '../utils/money'
import { formatDate } from '../utils/dates'
import { PhX } from '@phosphor-icons/vue'
import type { Expense } from '../types'
import BalanceSummary from '../components/BalanceSummary.vue'
import ExpenseFormDialog from '../components/ExpenseFormDialog.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import PageHeader from '../components/ui/PageHeader.vue'

const expensesStore = useExpensesStore()
const financeStore = useFinanceStore()
const settlementsStore = useSettlementsStore()
const { showToast } = useToast()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// ── Kategorie-Emoji-Mapping ──
const CATEGORY_EMOJI: Record<string, string> = {
  groceries: '🛒',
  housing: '🏠',
  cats: '🐈',
  leisure: '🎮',
  health: '💊',
  other: '📦',
}

function categoryEmoji(category: string | null): string {
  if (!category) return '💰'
  return CATEGORY_EMOJI[category] ?? '💰'
}

function categoryLabel(category: string | null): string {
  if (!category) return t('expenses.categories.uncategorized')
  return t(`expenses.categories.${category}`, category)
}

// ── User-Resolver ──
function resolveUserName(userId: string | null): string {
  if (!userId) return t('common.formerMember')
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.formerMember')
}

// ── Budget ──
const budgetExists = computed(() => financeStore.summary?.budget_rappen != null)
const budgetRappen = computed(() => financeStore.summary?.budget_rappen ?? 0)
const totalSpent = computed(() => financeStore.summary?.total_spent_rappen ?? 0)
const remaining = computed(() => financeStore.summary?.remaining_rappen ?? 0)
const isOverspent = computed(() => remaining.value < 0)
const spentPercent = computed(() => {
  if (!budgetRappen.value) return 0
  return Math.min((totalSpent.value / budgetRappen.value) * 100, 100)
})
const daysElapsed = computed(() => financeStore.summary?.days_elapsed ?? 0)

// ── Budget Inline Edit ──
const editingBudget = ref(false)
const budgetInput = ref('')
const savingBudget = ref(false)

function startBudgetEdit() {
  if (budgetExists.value) {
    budgetInput.value = (budgetRappen.value / 100).toFixed(2)
  } else {
    budgetInput.value = ''
  }
  editingBudget.value = true
}

function cancelBudgetEdit() {
  editingBudget.value = false
  budgetInput.value = ''
}

async function saveBudget() {
  const rappen = parseAmountToRappen(budgetInput.value)
  if (!rappen) {
    showToast(t('expenses.invalidAmount'), 'error')
    return
  }
  savingBudget.value = true
  try {
    const now = new Date()
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
    await financeStore.upsertBudget({ month, amount_rappen: rappen })
    showToast(t('finance.budgetSaved'), 'success')
    editingBudget.value = false
  } catch {
    showToast(t('common.error'), 'error')
  } finally {
    savingBudget.value = false
  }
}

// ── Kategorie-Chips ──
const categoryChips = computed(() => {
  const cats = financeStore.summary?.by_category ?? []
  return cats.map(c => ({
    key: c.category,
    emoji: categoryEmoji(c.category),
    label: categoryLabel(c.category),
    total: c.total_rappen,
  }))
})

// ── Pending Bills ──
const pendingBills = computed(() => {
  return financeStore.summary?.pending_bills ?? []
})

const hasBills = computed(() => pendingBills.value.length > 0)

const nextBillId = computed(() => {
  const today = new Date().getDate()
  const unbooked = pendingBills.value.filter(b => !b.is_booked_this_month)
  if (unbooked.length === 0) return null
  // Nächste nach heute
  const upcoming = unbooked.filter(b => b.day_of_month >= today)
  if (upcoming.length > 0) {
    return upcoming.sort((a, b) => a.day_of_month - b.day_of_month)[0].id
  }
  // Alle schon vorbei → nächste im Monat
  return unbooked.sort((a, b) => a.day_of_month - b.day_of_month)[0].id
})

const bookingBillId = ref<string | null>(null)

async function handleBookBill(billId: string) {
  bookingBillId.value = billId
  try {
    await financeStore.bookBill(billId)
    showToast(t('finance.billBooked'), 'success')
    // Refresh expenses too
    expensesStore.fetchExpenses()
  } catch (e: any) {
    const msg = e.response?.data?.detail
    if (typeof msg === 'string' && msg.includes('already booked')) {
      showToast(t('finance.billAlreadyBooked'), 'error')
    } else {
      showToast(t('common.error'), 'error')
    }
  } finally {
    bookingBillId.value = null
  }
}

// ── Expense Dialog ──
const showDialog = ref(false)
const editingExpense = ref<Expense | undefined>(undefined)
const autoOpen = computed(() => route.query.new === '1')

function openAddDialog() {
  editingExpense.value = undefined
  showDialog.value = true
}

function openEditDialog(expense: Expense) {
  editingExpense.value = expense
  showDialog.value = true
}

// ── Delete Expense ──
async function handleDeleteExpense(expenseId: string) {
  const expense = expensesStore.expenses.find(e => e.id === expenseId)
  if (!expense) return

  try {
    await expensesStore.removeExpense(expenseId)
    showToast(t('common.deleted'), 'success', undefined, {
      label: t('common.undo'),
      onAction: () => {
        expensesStore.addExpense({
          description: expense.description,
          amount_rappen: expense.amount_rappen,
          currency: expense.currency,
          paid_by_user_id: expense.paid_by_user_id!,
          expense_date: expense.expense_date,
          split_type: expense.split_type,
          category: expense.category ?? undefined,
          shares: expense.split_type === 'custom' ? expense.shares : undefined,
          participant_ids: expense.split_type === 'even' ? expense.shares.map(s => s.user_id) : undefined,
        }).catch(() => {
          showToast(t('expenses.submitError'), 'error')
        })
      },
    })
  } catch {
    showToast(t('expenses.deleteError'), 'error')
  }
}

// ── Delete Settlement ──
async function handleDeleteSettlement(settlementId: string) {
  const settlement = settlementsStore.settlements.find(s => s.id === settlementId)
  if (!settlement) return

  try {
    await settlementsStore.remove(settlementId)
    showToast(t('common.deleted'), 'success', undefined, {
      label: t('common.undo'),
      onAction: () => {
        settlementsStore.create({
          from_user_id: settlement.from_user_id,
          to_user_id: settlement.to_user_id,
          amount_rappen: settlement.amount_rappen,
          currency: settlement.currency,
          settled_date: settlement.settled_date,
          note: settlement.note ?? undefined,
        }).catch(() => {
          showToast(t('settlements.saveError'), 'error')
        })
      },
    })
  } catch {
    showToast(t('settlements.deleteError'), 'error')
  }
}

// ── Split-Type Label ──
function splitLabel(expense: Expense): string {
  return expense.split_type === 'even' ? t('expenses.splitEven') : t('expenses.splitCustom')
}

// ── Init ──
onMounted(() => {
  financeStore.fetchSummary()
  financeStore.fetchBills()
  financeStore.fetchBudget()
  expensesStore.fetchExpenses()
  expensesStore.fetchBalances()
  expensesStore.fetchMembers()
  settlementsStore.fetchAll()

  if (route.query.new === '1') {
    router.replace({ query: {} })
  }
  if (autoOpen.value) {
    openAddDialog()
  }
})
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('nav.expenses')" />

    <!-- ══════════════ 1. Kopfkarte "Noch verfügbar" ══════════════ -->
    <BaseCard padding="lg">
      <div class="budget-card">
        <!-- Budget wird geladen -->
        <template v-if="financeStore.loading && !financeStore.summary">
          <BaseSkeleton width="50%" height="28px" />
          <BaseSkeleton width="100%" height="8px" style="margin-top: 12px" />
          <BaseSkeleton width="60%" height="14px" style="margin-top: 8px" />
        </template>

        <!-- Budget vorhanden -->
        <template v-else-if="budgetExists && !editingBudget">
          <span class="budget-card__label">
            {{ isOverspent ? $t('finance.overspent') : $t('finance.available') }}
          </span>
          <button
            class="budget-card__amount"
            :class="{ 'budget-card__amount--danger': isOverspent }"
            @click="startBudgetEdit"
            :title="$t('finance.editBudget')"
          >
            {{ formatRappen(Math.abs(remaining)) }}
          </button>

          <!-- Fortschrittsbalken -->
          <div class="progress-bar">
            <div
              class="progress-bar__fill"
              :class="{ 'progress-bar__fill--danger': totalSpent > budgetRappen }"
              :style="{ width: spentPercent + '%' }"
            />
          </div>

          <span class="budget-card__sub">
            {{ $t('finance.budgetLine', { amount: formatRappen(budgetRappen), days: daysElapsed }) }}
          </span>
        </template>

        <!-- Kein Budget -->
        <template v-else-if="!budgetExists && !editingBudget">
          <span class="budget-card__label">{{ $t('finance.noBudget') }}</span>
          <span class="budget-card__amount budget-card__amount--muted">
            {{ formatRappen(totalSpent) }}
          </span>
          <span class="budget-card__sub">{{ $t('finance.noBudget') }}</span>
          <button class="budget-card__set-link" @click="startBudgetEdit">
            {{ $t('finance.setBudget') }}
          </button>
        </template>

        <!-- Budget Inline-Edit -->
        <template v-if="editingBudget">
          <span class="budget-card__label">{{ $t('finance.budgetAmount') }}</span>
          <div class="budget-edit">
            <input
              v-model="budgetInput"
              type="text"
              inputmode="decimal"
              class="budget-edit__input"
              :placeholder="$t('expenses.amountPlaceholder')"
              @keyup.enter="saveBudget"
              @keyup.escape="cancelBudgetEdit"
            />
            <BaseButton variant="primary" size="sm" :loading="savingBudget" @click="saveBudget">
              {{ $t('common.save') }}
            </BaseButton>
            <BaseButton variant="ghost" size="sm" @click="cancelBudgetEdit">
              {{ $t('common.cancel') }}
            </BaseButton>
          </div>
        </template>
      </div>
    </BaseCard>

    <!-- ══════════════ 2. Kategorie-Chips ══════════════ -->
    <div v-if="categoryChips.length > 0" class="category-scroll">
      <div class="category-scroll__inner">
        <span
          v-for="chip in categoryChips"
          :key="chip.key ?? 'uncategorized'"
          class="cat-chip"
        >
          {{ chip.emoji }} {{ chip.label }} {{ formatRappen(chip.total) }}
        </span>
      </div>
    </div>

    <!-- ══════════════ 3. Anstehende Rechnungen ══════════════ -->
    <BaseCard v-if="hasBills" padding="md">
      <h2 class="section-title">{{ $t('finance.pendingBills') }}</h2>

      <ul class="bills-list">
        <li
          v-for="bill in pendingBills"
          :key="bill.id"
          class="bill-row"
          :class="{ 'bill-row--next': bill.id === nextBillId && !bill.is_booked_this_month }"
        >
          <div class="bill-row__info">
            <span class="bill-row__name">{{ bill.name }}</span>
            <span class="bill-row__meta">
              {{ formatRappen(bill.amount_rappen) }} · {{ bill.day_of_month }}.
            </span>
          </div>
          <div class="bill-row__action">
            <span v-if="bill.is_booked_this_month" class="bill-badge">
              {{ $t('finance.booked') }} ✓
            </span>
            <BaseButton
              v-else
              variant="primary"
              size="sm"
              :loading="bookingBillId === bill.id"
              @click="handleBookBill(bill.id)"
            >
              {{ $t('finance.book') }}
            </BaseButton>
          </div>
        </li>
      </ul>

      <p
        v-if="pendingBills.every(b => b.is_booked_this_month)"
        class="section-sub"
      >
        {{ $t('finance.noPendingBills') }}
      </p>
    </BaseCard>

    <!-- ══════════════ 4. Letzte Ausgaben ══════════════ -->
    <BaseCard padding="md">
      <div class="expenses-header">
        <h2 class="section-title">{{ $t('finance.recentExpenses') }}</h2>
        <BaseButton variant="primary" size="sm" @click="openAddDialog">
          {{ $t('expenses.addExpense') }}
        </BaseButton>
      </div>

      <!-- Skeleton -->
      <div v-if="expensesStore.loading && expensesStore.expenses.length === 0" class="skeleton-list">
        <div class="skeleton-row" v-for="n in 3" :key="n">
          <BaseSkeleton width="32px" height="32px" rounded />
          <div style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
            <BaseSkeleton :width="['60%', '50%', '70%'][n - 1]" height="16px" />
            <BaseSkeleton width="45%" height="12px" />
          </div>
          <BaseSkeleton width="80px" height="16px" />
        </div>
      </div>

      <!-- Expense-Einträge -->
      <ul v-if="expensesStore.expenses.length > 0" class="expense-items">
        <li
          v-for="expense in expensesStore.expenses"
          :key="expense.id"
          class="expense-item"
        >
          <div class="expense-item__main" @click="openEditDialog(expense)">
            <span class="expense-item__emoji">{{ categoryEmoji(expense.category) }}</span>
            <div class="expense-item__body">
              <div class="expense-item__title-line">
                <span class="expense-item__desc">{{ expense.description }}</span>
                <span class="expense-item__amount">{{ formatRappen(expense.amount_rappen) }}</span>
              </div>
              <div class="expense-item__meta">
                <BaseAvatar
                  v-if="expense.paid_by_user_id"
                  :name="resolveUserName(expense.paid_by_user_id)"
                  :user-id="expense.paid_by_user_id"
                  size="sm"
                />
                <span>{{ resolveUserName(expense.paid_by_user_id) }}</span>
                <span class="expense-item__split-badge">{{ splitLabel(expense) }}</span>
              </div>
            </div>
          </div>
          <button
            class="action-btn action-btn--danger"
            @click.stop="handleDeleteExpense(expense.id)"
            :title="$t('common.delete')"
            :aria-label="$t('common.delete')"
          >
            <PhX :size="16" />
          </button>
        </li>
      </ul>

      <!-- Empty State -->
      <p
        v-if="!expensesStore.loading && expensesStore.expenses.length === 0"
        class="section-sub"
      >
        {{ $t('expenses.emptySubtitle') }}
      </p>
    </BaseCard>

    <!-- ══════════════ 5. Salden & Ausgleich ══════════════ -->
    <BalanceSummary />

    <!-- ══════════════ 6. Settlements ══════════════ -->
    <BaseCard v-if="settlementsStore.loading && settlementsStore.settlements.length === 0">
      <div class="skeleton-list">
        <div class="skeleton-row" v-for="n in 2" :key="n">
          <BaseSkeleton width="22px" height="22px" rounded />
          <BaseSkeleton width="60%" height="14px" />
          <BaseSkeleton width="80px" height="14px" />
        </div>
      </div>
    </BaseCard>

    <BaseCard v-if="settlementsStore.settlements.length > 0">
      <h2 class="section-title">{{ $t('settlements.title') }}</h2>
      <ul class="settlement-list">
        <li
          v-for="s in settlementsStore.settlements"
          :key="s.id"
          class="settlement-item"
        >
          <div class="settlement-item__main">
            <div class="settlement-item__flow">
              <BaseAvatar :name="resolveUserName(s.from_user_id)" :user-id="s.from_user_id" size="sm" />
              <strong>{{ resolveUserName(s.from_user_id) }}</strong>
              →
              <BaseAvatar :name="resolveUserName(s.to_user_id)" :user-id="s.to_user_id" size="sm" />
              <strong>{{ resolveUserName(s.to_user_id) }}</strong>
            </div>
            <span class="settlement-item__amount">{{ formatRappen(s.amount_rappen) }}</span>
          </div>
          <div class="settlement-item__meta">
            <span>{{ formatDate(s.settled_date) }}</span>
            <span v-if="s.note" class="settlement-item__note">{{ s.note }}</span>
          </div>
          <button
            class="action-btn action-btn--danger"
            @click="handleDeleteSettlement(s.id)"
            :title="$t('common.delete')"
            :aria-label="$t('settlements.deleteConfirm')"
          >
            <PhX :size="16" />
          </button>
        </li>
      </ul>
    </BaseCard>

    <!-- ══════════════ Expense Dialog ══════════════ -->
    <ExpenseFormDialog
      v-model="showDialog"
      :expense="editingExpense"
    />
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Budget-Kopfkarte ── */
.budget-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.budget-card__label {
  font-size: var(--text-sm);
  color: var(--sub);
  font-weight: var(--font-weight-medium);
}

.budget-card__amount {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  color: var(--ok);
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
  line-height: var(--line-height-tight);
}

.budget-card__amount--danger {
  color: var(--color-danger);
}

.budget-card__amount--muted {
  color: var(--sub);
  cursor: default;
}

.budget-card__sub {
  font-size: var(--text-sm);
  color: var(--sub);
}

.budget-card__set-link {
  background: none;
  border: none;
  padding: 0;
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--p1);
  cursor: pointer;
  text-align: left;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.budget-card__set-link:hover {
  color: var(--acc);
}

/* Progress Bar */
.progress-bar {
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--chip);
  overflow: hidden;
  margin: var(--space-1) 0;
}

.progress-bar__fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--ok);
  transition: width var(--transition-normal);
}

.progress-bar__fill--danger {
  background: var(--color-danger);
}

/* Budget Inline Edit */
.budget-edit {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.budget-edit__input {
  flex: 1;
  max-width: 160px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-size: var(--text-base);
  color: var(--ink);
  background: var(--card);
}

.budget-edit__input:focus {
  outline: none;
  border-color: var(--p1);
  box-shadow: 0 0 0 3px var(--chip);
}

/* ── Kategorie-Chips ── */
.category-scroll {
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

.category-scroll::-webkit-scrollbar {
  display: none;
}

.category-scroll__inner {
  display: flex;
  gap: var(--space-2);
  padding: 0 var(--space-1);
}

.cat-chip {
  scroll-snap-align: start;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  background: var(--chip);
  border-radius: var(--radius-full);
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  color: var(--ink);
  white-space: nowrap;
  font-weight: var(--font-weight-medium);
}

/* ── Section Title ── */
.section-title {
  margin: 0 0 var(--space-3) 0;
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.section-sub {
  margin: var(--space-2) 0 0 0;
  font-size: var(--text-sm);
  color: var(--sub);
}

/* ── Bills ── */
.bills-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.bill-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--card);
  transition: background var(--transition-fast);
}

.bill-row--next {
  background: var(--acc-soft);
}

.bill-row__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.bill-row__name {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bill-row__meta {
  font-size: var(--text-sm);
  color: var(--sub);
}

.bill-row__action {
  flex-shrink: 0;
}

.bill-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--ok);
  background: var(--chip);
  border-radius: var(--radius-full);
  white-space: nowrap;
}

/* ── Expenses Header ── */
.expenses-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.expenses-header .section-title {
  margin: 0;
}

/* ── Expense Items ── */
.expense-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.expense-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--line);
}

.expense-item:last-child {
  border-bottom: none;
}

.expense-item__main {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
  cursor: pointer;
  -webkit-user-select: none;
  user-select: none;
}

.expense-item__emoji {
  font-size: var(--text-lg);
  line-height: 1;
  flex-shrink: 0;
  margin-top: 2px;
}

.expense-item__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.expense-item__title-line {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-2);
}

.expense-item__desc {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expense-item__amount {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  white-space: nowrap;
  flex-shrink: 0;
}

.expense-item__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--sub);
  margin-top: 2px;
}

.expense-item__split-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px var(--space-2);
  font-size: var(--text-xs);
  background: var(--chip);
  border-radius: var(--radius-full);
  color: var(--sub);
  white-space: nowrap;
}

/* ── Settlements ── */
.settlement-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.settlement-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--chip);
  transition: background var(--transition-fast);
}

.settlement-item:hover {
  filter: brightness(0.97);
}

.settlement-item__main {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.settlement-item__flow {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--ink);
}

.settlement-item__amount {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ok);
  white-space: nowrap;
}

.settlement-item__meta {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--sub);
}

.settlement-item__note {
  font-style: italic;
}

/* ── Action Button ── */
.action-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
  background: transparent;
  color: var(--sub);
}

.action-btn--danger:hover {
  background: var(--color-danger);
  color: var(--card);
}

/* ── Skeleton ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
</style>
