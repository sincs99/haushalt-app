<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useExpensesStore } from '../stores/expenses'
import { useSettlementsStore } from '../stores/settlements'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { formatRappen, parseAmountToRappen } from '../utils/money'
import { householdDateString } from '../utils/dates'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseDialog from './ui/BaseDialog.vue'
import BaseErrorState from './ui/BaseErrorState.vue'
import type { SettlementEntry, SettlementWarning } from '../types'

const authStore = useAuthStore()
const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const { notifySuccess, notifyError, notifyInfo } = useToast()
const { t } = useI18n()

function resolveUserName(userId: string): string {
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.formerMember')
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
const settlementFormId = `settlement-form-${Math.random().toString(36).slice(2, 9)}`
// Client-ID pro geöffnetem Dialog: Retry/Doppelklick legt keinen zweiten Ausgleich an (CASA-08)
const dialogClientId = ref('')
// Plausibilitätswarnungen (PD-F3): einmal anzeigen, zweiter Klick speichert trotzdem
const dialogWarnings = ref<SettlementWarning[]>([])
const dialogOpenDebt = ref(0)
const acknowledgedKey = ref('')

// Eingaben geändert → Warnungen gelten nicht mehr
watch([dialogFrom, dialogTo, dialogAmount], () => {
  dialogWarnings.value = []
  acknowledgedKey.value = ''
})

function warningText(w: SettlementWarning): string {
  return t(`settlements.warnings.${w}`, { amount: formatRappen(dialogOpenDebt.value) })
}

// Salden erneut laden (nach Ladefehler)
const retryingBalances = ref(false)
async function retryBalances() {
  retryingBalances.value = true
  try {
    await expensesStore.fetchBalances()
  } finally {
    retryingBalances.value = false
  }
}

function openSettlementDialog(s: SettlementEntry) {
  dialogFrom.value = s.from_user_id
  dialogTo.value = s.to_user_id
  dialogAmount.value = (s.amount_rappen / 100).toFixed(2)
  // Haushaltsdatum (Zeitzone aus /me), sonst lokales Gerätedatum (CASA-39)
  dialogDate.value = householdDateString(authStore.currentHousehold?.timezone)
  dialogNote.value = ''
  dialogClientId.value = crypto.randomUUID()
  dialogWarnings.value = []
  acknowledgedKey.value = ''
  showSettlementDialog.value = true
}

async function confirmSettlement() {
  // Doppelt-Senden verhindern (Enter + Klick)
  if (settlementSaving.value) return
  const rappen = parseAmountToRappen(dialogAmount.value)
  if (!rappen) {
    notifyError(t('settlements.invalidAmount'))
    return
  }
  if (dialogFrom.value === dialogTo.value) {
    notifyError(t('settlements.sameUser'))
    return
  }
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    notifyInfo(t('offline.actionBlocked'))
    return
  }

  const payload = {
    id: dialogClientId.value || undefined,
    from_user_id: dialogFrom.value,
    to_user_id: dialogTo.value,
    amount_rappen: rappen,
    settled_date: dialogDate.value || undefined,
    note: dialogNote.value.trim() || undefined,
  }
  const key = `${payload.from_user_id}|${payload.to_user_id}|${rappen}`

  settlementSaving.value = true
  try {
    // Erst prüfen (doppelt erfasst? mehr als die offene Schuld?) — warnen, nicht verbieten
    if (acknowledgedKey.value !== key) {
      const check = await settlementsStore.check(payload)
      if (check && check.warnings.length > 0) {
        dialogWarnings.value = check.warnings
        dialogOpenDebt.value = check.open_debt_rappen
        acknowledgedKey.value = key
        return
      }
    }
    const created = await settlementsStore.create(payload)
    // Gleichzeitig von der Gegenseite erfasst → gespeichert, aber deutlich darauf hinweisen
    if (created?.warnings?.includes('DUPLICATE_RECENT') && !dialogWarnings.value.includes('DUPLICATE_RECENT')) {
      notifyInfo(t('settlements.createdWithWarning'))
    } else {
      notifySuccess(t('settlements.created'))
    }
    showSettlementDialog.value = false
  } catch (e) {
    notifyError(t('settlements.saveError'), e)
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
        <div class="balance-row__left">
          <BaseAvatar :name="resolveUserName(entry.user_id)" :user-id="entry.user_id" size="sm" />
          <span class="balance-row__name">{{ resolveUserName(entry.user_id) }}</span>
        </div>
        <span class="balance-row__saldo" :style="{ color: saldoColor(entry.saldo_rappen) }">
          {{ formatSaldo(entry.saldo_rappen) }}
        </span>
      </div>

      <!-- Ausgleich-Sektion -->
      <div v-if="hasSettlements" class="settlement-section">
        <h3 class="settlement-section__title">{{ $t('expenses.balance.settlementTitle') }}</h3>
        <div
          v-for="(s, idx) in expensesStore.balances.settlements"
          :key="idx"
          class="settlement-row"
        >
          <span>
            <strong>{{ resolveUserName(s.from_user_id) }}</strong>
            {{ $t('expenses.balance.pays') }}
            <strong>{{ resolveUserName(s.to_user_id) }}</strong>:
            {{ formatRappen(s.amount_rappen) }}
          </span>
          <button class="mark-paid-btn tap-target" @click="openSettlementDialog(s)">
            {{ $t('settlements.markAsPaid') }}
          </button>
        </div>
      </div>

      <!-- Alles ausgeglichen -->
      <p v-if="allSettled" class="settled-message">
        {{ $t('expenses.balance.settled') }}
      </p>

      <!-- Unassigned-Hinweis -->
      <p v-if="unassignedRappen > 0" class="unassigned-hint">
        {{ $t('expenses.balance.unassignedHint', { amount: formatRappen(unassignedRappen) }) }}
      </p>
    </div>
  </BaseCard>

  <!-- Salden konnten nicht geladen werden: Karte nicht still verschwinden lassen -->
  <BaseCard v-else-if="expensesStore.balancesError" padding="md">
    <BaseErrorState
      :message="$t('expenses.balance.loadError')"
      :retrying="retryingBalances"
      @retry="retryBalances"
    />
  </BaseCard>

  <!-- Settlement-Bestätigungsdialog -->
  <BaseDialog
    :open="showSettlementDialog"
    :title="$t('settlements.dialogTitle')"
    @close="showSettlementDialog = false"
  >
    <form :id="settlementFormId" class="dialog-form" @submit.prevent="confirmSettlement">
      <label class="dialog-label">
        {{ $t('settlements.from') }}
        <select v-model="dialogFrom" class="dialog-select">
          <option v-for="m in expensesStore.members" :key="m.id" :value="m.id">{{ m.display_name }}</option>
        </select>
      </label>
      <label class="dialog-label">
        {{ $t('settlements.to') }}
        <select v-model="dialogTo" class="dialog-select">
          <option v-for="m in expensesStore.members" :key="m.id" :value="m.id">{{ m.display_name }}</option>
        </select>
      </label>
      <label class="dialog-label">
        {{ $t('settlements.amount') }}
        <input v-model="dialogAmount" type="text" inputmode="decimal" class="dialog-input" />
      </label>
      <label class="dialog-label">
        {{ $t('settlements.date') }}
        <input v-model="dialogDate" type="date" class="dialog-input" />
      </label>
      <label class="dialog-label">
        {{ $t('settlements.note') }}
        <input v-model="dialogNote" type="text" maxlength="200" class="dialog-input" :placeholder="$t('settlements.notePlaceholder')" />
      </label>

      <!-- Plausibilitätswarnungen (PD-F3) -->
      <div v-if="dialogWarnings.length > 0" class="settlement-warning" role="alert">
        <strong>{{ $t('settlements.warningTitle') }}</strong>
        <ul>
          <li v-for="w in dialogWarnings" :key="w">{{ warningText(w) }}</li>
        </ul>
      </div>
    </form>
    <template #footer>
      <BaseButton variant="ghost" size="sm" @click="showSettlementDialog = false">{{ $t('common.cancel') }}</BaseButton>
      <BaseButton variant="primary" size="sm" type="submit" :form="settlementFormId" :loading="settlementSaving">
        {{ dialogWarnings.length > 0 ? $t('settlements.saveAnyway') : $t('settlements.confirm') }}
      </BaseButton>
    </template>
  </BaseDialog>
</template>

<style scoped>
.settlement-warning {
  padding: var(--space-3);
  background: var(--color-warning-soft);
  border-radius: var(--radius-sm);
  color: var(--color-warning-strong);
  font-size: var(--text-sm);
}

.settlement-warning ul {
  margin: var(--space-1) 0 0;
  padding-left: var(--space-4);
}

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

.balance-row__left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
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
  border-top: 1px solid var(--line);
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
  color: var(--color-on-success);
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
  border-top: 1px solid var(--line);
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
  border: 1px solid var(--line-strong);
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

</style>
