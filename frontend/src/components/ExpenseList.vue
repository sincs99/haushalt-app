<script setup lang="ts">
import { ref } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { formatRappen } from '../utils/money'
import type { Expense } from '../types'
import BaseButton from './ui/BaseButton.vue'
import BaseSpinner from './ui/BaseSpinner.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'
import ExpenseFormDialog from './ExpenseFormDialog.vue'

const expensesStore = useExpensesStore()
const { showToast } = useToast()
const { t } = useI18n()

// Dialog State
const showDialog = ref(false)
const editingExpense = ref<Expense | undefined>(undefined)

function openAddDialog() {
  editingExpense.value = undefined
  showDialog.value = true
}

function openEditDialog(expense: Expense) {
  editingExpense.value = expense
  showDialog.value = true
}

function resolveUserName(userId: string | null): string {
  if (!userId) return t('common.formerMember')
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.formerMember')
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  const locale = localStorage.getItem('haushalt_locale') ?? 'de'
  const intlLocale = locale === 'de' ? 'de-CH' : 'en-CH'
  return d.toLocaleDateString(intlLocale, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

async function handleDelete(expenseId: string) {
  try {
    await expensesStore.removeExpense(expenseId)
  } catch {
    showToast(t('expenses.deleteError'), 'error')
  }
}
</script>

<template>
  <div class="expense-list">
    <!-- Sticky Add-Button -->
    <div class="quick-add">
      <BaseButton variant="primary" @click="openAddDialog">
        {{ $t('expenses.addExpense') }}
      </BaseButton>
    </div>

    <!-- Loading -->
    <div v-if="expensesStore.loading" class="loading-center">
      <BaseSpinner />
    </div>

    <!-- Expense-Einträge -->
    <ul v-if="expensesStore.expenses.length > 0" class="item-list">
      <li
        v-for="expense in expensesStore.expenses"
        :key="expense.id"
        class="expense-row"
      >
        <div class="expense-row__main" @click="openEditDialog(expense)">
          <div class="expense-row__content">
            <div class="expense-row__title-line">
              <span class="expense-row__desc">{{ expense.description }}</span>
              <span class="expense-row__amount">{{ formatRappen(expense.amount_rappen) }}</span>
            </div>
            <div class="expense-row__meta">
              <span class="expense-row__date">{{ formatDate(expense.expense_date) }}</span>
              <span class="expense-row__paid-by">
                {{ $t('expenses.paidBy', { name: resolveUserName(expense.paid_by_user_id) }) }}
              </span>
            </div>
          </div>
        </div>
        <div class="expense-row__actions">
          <button
            class="action-btn action-btn--danger"
            @click.stop="handleDelete(expense.id)"
            :title="$t('common.delete')"
            :aria-label="$t('common.delete')"
          >
            ✕
          </button>
        </div>
      </li>
    </ul>

    <!-- Empty State -->
    <BaseEmptyState
      v-if="!expensesStore.loading && expensesStore.expenses.length === 0"
      icon="💰"
      :title="$t('expenses.emptyTitle')"
      :subtitle="$t('expenses.emptySubtitle')"
    />

    <!-- Dialog -->
    <ExpenseFormDialog
      v-model="showDialog"
      :expense="editingExpense"
    />
  </div>
</template>

<style scoped>
.expense-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Quick-Add: sticky */
.quick-add {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--color-bg);
  padding-bottom: var(--space-2);
}

@media (min-width: 768px) {
  .quick-add {
    position: static;
  }
}

/* Loading */
.loading-center {
  display: flex;
  justify-content: center;
  padding: var(--space-8) 0;
}

/* Item-Liste */
.item-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

/* Expense-Zeile */
.expense-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--color-neutral-100);
}

.expense-row__main {
  display: flex;
  align-items: flex-start;
  flex: 1;
  cursor: pointer;
  min-height: 44px;
  -webkit-user-select: none;
  user-select: none;
}

.expense-row__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.expense-row__title-line {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-2);
}

.expense-row__desc {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expense-row__amount {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  white-space: nowrap;
  flex-shrink: 0;
}

.expense-row__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-top: 2px;
}

.expense-row__date {
  white-space: nowrap;
}

.expense-row__paid-by {
  white-space: nowrap;
}

/* Actions */
.expense-row__actions {
  display: flex;
  flex-shrink: 0;
}

.action-btn {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: var(--text-base);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
  min-width: 44px;
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-btn:hover {
  background: var(--color-neutral-100);
  color: var(--color-primary);
}

.action-btn--danger:hover {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

@media (hover: hover) {
  .expense-row__main:hover {
    background: var(--color-neutral-50);
    border-radius: var(--radius-sm);
  }
}
</style>
