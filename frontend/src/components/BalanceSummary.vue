<script setup lang="ts">
import { computed } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import { formatRappen } from '../utils/money'
import BaseCard from './ui/BaseCard.vue'

const expensesStore = useExpensesStore()

function resolveUserName(userId: string): string {
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? 'Ehemaliges Mitglied'
}

const hasExpenses = computed(() => expensesStore.expenses.length > 0)
const hasSettlements = computed(() => (expensesStore.balances?.settlements.length ?? 0) > 0)
const allSettled = computed(() => !hasSettlements.value && hasExpenses.value)
const unassignedRappen = computed(() => expensesStore.balances?.unassigned_rappen ?? 0)

function formatSaldo(rappen: number): string {
  if (rappen > 0) return `+ ${formatRappen(rappen)}`
  if (rappen < 0) return `- ${formatRappen(Math.abs(rappen))}`
  return formatRappen(0)
}

function saldoColor(rappen: number): string {
  if (rappen > 0) return 'var(--color-success)'
  if (rappen < 0) return 'var(--color-danger)'
  return 'var(--color-text-secondary)'
}
</script>

<template>
  <BaseCard v-if="expensesStore.balances" padding="md">
    <div class="balance-summary">
      <!-- Salden pro Mitglied -->
      <div
        v-for="entry in expensesStore.balances.balances"
        :key="entry.user_id"
        class="balance-row"
      >
        <span class="balance-row__name">{{ resolveUserName(entry.user_id) }}</span>
        <span class="balance-row__saldo" :style="{ color: saldoColor(entry.saldo_rappen) }">
          {{ formatSaldo(entry.saldo_rappen) }}
        </span>
      </div>

      <!-- Ausgleich-Sektion -->
      <div v-if="hasSettlements" class="settlement-section">
        <h3 class="settlement-section__title">Ausgleich</h3>
        <div
          v-for="(s, idx) in expensesStore.balances.settlements"
          :key="idx"
          class="settlement-row"
        >
          <span>
            <strong>{{ resolveUserName(s.from_user_id) }}</strong>
            zahlt
            <strong>{{ resolveUserName(s.to_user_id) }}</strong>:
            {{ formatRappen(s.amount_rappen) }}
          </span>
        </div>
      </div>

      <!-- Alles ausgeglichen -->
      <p v-if="allSettled" class="settled-message">
        ✓ Alles ausgeglichen
      </p>

      <!-- Unassigned-Hinweis -->
      <p v-if="unassignedRappen > 0" class="unassigned-hint">
        {{ formatRappen(unassignedRappen) }} von ehemaligen Mitgliedern nicht zuordenbar
      </p>
    </div>
  </BaseCard>
</template>

<style scoped>
.balance-summary {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.balance-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-1) 0;
}

.balance-row__name {
  font-size: var(--text-base);
  color: var(--color-text);
}

.balance-row__saldo {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.settlement-section {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-neutral-200);
}

.settlement-section__title {
  margin: 0 0 var(--space-2) 0;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.settlement-row {
  font-size: var(--text-sm);
  color: var(--color-text);
  padding: var(--space-1) 0;
}

.settled-message {
  margin: var(--space-2) 0 0 0;
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-neutral-200);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-success);
}

.unassigned-hint {
  margin: var(--space-2) 0 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}
</style>
