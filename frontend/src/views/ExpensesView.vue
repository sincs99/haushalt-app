<script setup lang="ts">
import { onMounted } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import { useSettlementsStore } from '../stores/settlements'
import { useToast } from '../composables/useToast'
import { formatRappen } from '../utils/money'
import ExpenseList from '../components/ExpenseList.vue'
import BalanceSummary from '../components/BalanceSummary.vue'
import BaseCard from '../components/ui/BaseCard.vue'

const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const { showToast } = useToast()

function resolveUserName(userId: string | null): string {
  if (!userId) return 'Ehemaliges Mitglied'
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? 'Ehemaliges Mitglied'
}

function formatDateDE(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

async function handleDeleteSettlement(settlementId: string) {
  if (!confirm('Ausgleichszahlung wirklich löschen?')) return
  try {
    await settlementsStore.remove(settlementId)
  } catch {
    showToast('Zahlung konnte nicht gelöscht werden.', 'error')
  }
}

onMounted(() => {
  expensesStore.fetchExpenses()
  expensesStore.fetchBalances()
  expensesStore.fetchMembers()
  settlementsStore.fetchAll()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">💰 Ausgaben</h1>
    <BalanceSummary />
    <ExpenseList />

    <!-- Settlement-Liste -->
    <BaseCard v-if="settlementsStore.settlements.length > 0">
      <h2 class="section-title">Ausgleichszahlungen</h2>
      <ul class="settlement-list">
        <li
          v-for="s in settlementsStore.settlements"
          :key="s.id"
          class="settlement-item"
        >
          <div class="settlement-item__main">
            <div class="settlement-item__flow">
              <strong>{{ resolveUserName(s.from_user_id) }}</strong>
              →
              <strong>{{ resolveUserName(s.to_user_id) }}</strong>
            </div>
            <span class="settlement-item__amount">{{ formatRappen(s.amount_rappen) }}</span>
          </div>
          <div class="settlement-item__meta">
            <span>{{ formatDateDE(s.settled_date) }}</span>
            <span v-if="s.note" class="settlement-item__note">{{ s.note }}</span>
          </div>
          <button
            class="action-btn action-btn--danger"
            @click="handleDeleteSettlement(s.id)"
            title="Löschen"
            aria-label="Ausgleichszahlung löschen"
          >
            ✕
          </button>
        </li>
      </ul>
    </BaseCard>
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.view-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
}

.section-title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

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
  background: var(--color-neutral-50);
  transition: background var(--transition-fast);
}

.settlement-item:hover {
  background: var(--color-neutral-100);
}

.settlement-item__main {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.settlement-item__flow {
  font-size: var(--text-sm);
  color: var(--color-text);
}

.settlement-item__amount {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-success);
  white-space: nowrap;
}

.settlement-item__meta {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.settlement-item__note {
  font-style: italic;
}

.action-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.action-btn--danger {
  background: transparent;
  color: var(--color-text-muted);
}

.action-btn--danger:hover {
  background: var(--color-danger);
  color: var(--color-surface);
}
</style>
