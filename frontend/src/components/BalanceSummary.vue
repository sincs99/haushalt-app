<script setup lang="ts">
import { computed, ref } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import { useSettlementsStore } from '../stores/settlements'
import { useToast } from '../composables/useToast'
import { formatRappen, parseAmountToRappen } from '../utils/money'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import type { SettlementEntry } from '../types'

const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const { showToast } = useToast()

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

// ── Settlement-Dialog ──
const showSettlementDialog = ref(false)
const dialogFrom = ref('')
const dialogTo = ref('')
const dialogAmount = ref('')
const dialogDate = ref('')
const dialogNote = ref('')
const settlementSaving = ref(false)

function todayISO(): string {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}

function openSettlementDialog(s: SettlementEntry) {
  dialogFrom.value = s.from_user_id
  dialogTo.value = s.to_user_id
  dialogAmount.value = (s.amount_rappen / 100).toFixed(2)
  dialogDate.value = todayISO()
  dialogNote.value = ''
  showSettlementDialog.value = true
}

async function confirmSettlement() {
  const rappen = parseAmountToRappen(dialogAmount.value)
  if (!rappen) {
    showToast('Bitte einen gültigen Betrag eingeben.', 'error')
    return
  }
  if (dialogFrom.value === dialogTo.value) {
    showToast('Von und An dürfen nicht identisch sein.', 'error')
    return
  }

  settlementSaving.value = true
  try {
    await settlementsStore.create({
      from_user_id: dialogFrom.value,
      to_user_id: dialogTo.value,
      amount_rappen: rappen,
      settled_date: dialogDate.value || undefined,
      note: dialogNote.value.trim() || undefined,
    })
    showToast('Ausgleichszahlung erfasst ✓', 'success')
    showSettlementDialog.value = false
  } catch {
    showToast('Zahlung konnte nicht gespeichert werden.', 'error')
  } finally {
    settlementSaving.value = false
  }
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
          <button class="mark-paid-btn" @click="openSettlementDialog(s)">
            ✓ Als bezahlt markieren
          </button>
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

  <!-- Settlement-Bestätigungsdialog -->
  <Teleport to="body">
    <div v-if="showSettlementDialog" class="dialog-backdrop" @click.self="showSettlementDialog = false">
      <div class="dialog-panel">
        <h3 class="dialog-title">Ausgleichszahlung erfassen</h3>
        <div class="dialog-form">
          <label class="dialog-label">
            Von
            <select v-model="dialogFrom" class="dialog-select">
              <option v-for="m in expensesStore.members" :key="m.id" :value="m.id">{{ m.display_name }}</option>
            </select>
          </label>
          <label class="dialog-label">
            An
            <select v-model="dialogTo" class="dialog-select">
              <option v-for="m in expensesStore.members" :key="m.id" :value="m.id">{{ m.display_name }}</option>
            </select>
          </label>
          <label class="dialog-label">
            Betrag (CHF)
            <input v-model="dialogAmount" type="text" inputmode="decimal" class="dialog-input" />
          </label>
          <label class="dialog-label">
            Datum
            <input v-model="dialogDate" type="date" class="dialog-input" />
          </label>
          <label class="dialog-label">
            Notiz (optional)
            <input v-model="dialogNote" type="text" maxlength="200" class="dialog-input" placeholder="z.B. Twint-Zahlung" />
          </label>
        </div>
        <div class="dialog-actions">
          <BaseButton variant="ghost" size="sm" @click="showSettlementDialog = false">Abbrechen</BaseButton>
          <BaseButton variant="primary" size="sm" @click="confirmSettlement" :loading="settlementSaving">Zahlung erfassen</BaseButton>
        </div>
      </div>
    </div>
  </Teleport>
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
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text);
  padding: var(--space-1) 0;
}

.mark-paid-btn {
  flex-shrink: 0;
  padding: var(--space-1) var(--space-2);
  background: var(--color-success);
  color: var(--color-surface);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background-color var(--transition-fast);
  white-space: nowrap;
}

.mark-paid-btn:hover {
  opacity: 0.9;
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

/* ── Settlement-Dialog ── */
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
}

.dialog-panel {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-overlay);
  width: 100%;
  max-width: 400px;
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.dialog-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.dialog-label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.dialog-select,
.dialog-input {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
}

.dialog-select:focus,
.dialog-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
