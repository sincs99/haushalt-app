<script setup lang="ts">
/**
 * Verwaltung der wiederkehrenden Rechnungen (P3): anlegen, bearbeiten, pausieren, löschen,
 * Standard-Zahler wählen. Gebucht wird weiterhin über „Anstehende Rechnungen“.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useFinanceStore } from '../stores/finance'
import { useExpensesStore } from '../stores/expenses'
import { useAsyncAction } from '../composables/useAsyncAction'
import { formatRappen, parseAmountToRappen } from '../utils/money'
import { PhPencilSimple, PhX } from '@phosphor-icons/vue'
import type { RecurringBill, RecurringBillUpdatePayload } from '../types'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseDialog from './ui/BaseDialog.vue'
import BaseInput from './ui/BaseInput.vue'

const financeStore = useFinanceStore()
const expensesStore = useExpensesStore()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const CATEGORIES = ['groceries', 'housing', 'cats', 'leisure', 'health', 'other'] as const

const bills = computed(() =>
  [...financeStore.bills].sort((a, b) => a.day_of_month - b.day_of_month || a.name.localeCompare(b.name)),
)

function payerName(userId: string | null): string {
  if (!userId) return t('finance.billNoDefaultPayer')
  return expensesStore.members.find(m => m.id === userId)?.display_name ?? t('common.formerMember')
}

// ── Formular ──
const formOpen = ref(false)
const editing = ref<RecurringBill | null>(null)
const name = ref('')
const amountText = ref('')
const day = ref('1')
const category = ref<string | null>(null)
const payerId = ref('')
const active = ref(true)
const formError = ref('')
const formId = `bill-form-${Math.random().toString(36).slice(2, 9)}`

const parsedAmount = computed(() => parseAmountToRappen(amountText.value))
const parsedDay = computed(() => {
  const n = Number(day.value)
  return Number.isInteger(n) && n >= 1 && n <= 28 ? n : null
})
const canSubmit = computed(() => !!name.value.trim() && parsedAmount.value !== null && parsedDay.value !== null)

function openCreate() {
  editing.value = null
  name.value = ''
  amountText.value = ''
  day.value = '1'
  category.value = null
  payerId.value = ''
  active.value = true
  formError.value = ''
  formOpen.value = true
}

function openEdit(bill: RecurringBill) {
  editing.value = bill
  name.value = bill.name
  amountText.value = (bill.amount_rappen / 100).toFixed(2)
  day.value = String(bill.day_of_month)
  category.value = bill.category
  // Ex-Mitglied als Standard-Zahler → wie „keiner“ behandeln (beim Buchen wählen)
  payerId.value = bill.paid_by_user_id && expensesStore.members.some(m => m.id === bill.paid_by_user_id)
    ? bill.paid_by_user_id
    : ''
  active.value = bill.active
  formError.value = ''
  formOpen.value = true
}

async function submit() {
  if (!canSubmit.value) {
    formError.value = parsedDay.value === null ? t('finance.billDayInvalid') : t('expenses.invalidAmount')
    return
  }
  const values = {
    name: name.value.trim(),
    amount_rappen: parsedAmount.value!,
    day_of_month: parsedDay.value!,
    category: category.value,
    paid_by_user_id: payerId.value || null,
    active: active.value,
  }
  const bill = editing.value
  const ok = await run(async () => {
    if (!bill) return financeStore.createBill(values)
    // Nur geänderte Felder senden
    const patch: RecurringBillUpdatePayload = {}
    for (const key of Object.keys(values) as (keyof typeof values)[]) {
      if (values[key] !== (bill[key] ?? null)) (patch as Record<string, unknown>)[key] = values[key]
    }
    return Object.keys(patch).length ? financeStore.updateBill(bill.id, patch) : bill
  }, {
    key: 'bill-form',
    success: t('finance.billSaved'),
    error: t('finance.billSaveError'),
  })
  if (ok) formOpen.value = false
}

// ── Löschen ──
const deleting = ref<RecurringBill | null>(null)

async function confirmDelete() {
  const bill = deleting.value
  if (!bill) return
  const ok = await run(() => financeStore.removeBill(bill.id), {
    key: `bill-delete-${bill.id}`,
    success: t('finance.billDeleted'),
    error: t('finance.billDeleteError'),
  })
  if (ok) deleting.value = null
}
</script>

<template>
  <BaseCard padding="md">
    <div class="bills-header">
      <h2 class="section-title">{{ $t('finance.recurringBills') }}</h2>
      <BaseButton variant="secondary" size="sm" @click="openCreate">{{ $t('finance.addBill') }}</BaseButton>
    </div>

    <p v-if="bills.length === 0" class="section-sub">{{ $t('finance.billsEmpty') }}</p>

    <ul v-else class="manage-list">
      <li v-for="bill in bills" :key="bill.id" class="manage-row" :class="{ 'manage-row--paused': !bill.active }">
        <div class="manage-row__info">
          <span class="manage-row__name">
            {{ bill.name }}
            <span v-if="!bill.active" class="paused-badge">{{ $t('finance.billPaused') }}</span>
          </span>
          <span class="manage-row__meta">
            {{ $t('finance.billMeta', { amount: formatRappen(bill.amount_rappen), day: bill.day_of_month, payer: payerName(bill.paid_by_user_id) }) }}
          </span>
        </div>
        <button
          class="icon-btn tap-target"
          :title="$t('common.edit')"
          :aria-label="$t('finance.billEditLabel', { name: bill.name })"
          @click="openEdit(bill)"
        >
          <PhPencilSimple :size="16" />
        </button>
        <button
          class="icon-btn icon-btn--danger tap-target"
          :title="$t('common.delete')"
          :aria-label="$t('finance.billDeleteConfirm', { name: bill.name })"
          @click="deleting = bill"
        >
          <PhX :size="16" />
        </button>
      </li>
    </ul>
  </BaseCard>

  <!-- Anlegen / Bearbeiten -->
  <BaseDialog :open="formOpen" :title="editing ? $t('finance.editBill') : $t('finance.newBill')" @close="formOpen = false">
    <form :id="formId" class="bill-form" novalidate @submit.prevent="submit">
      <BaseInput v-model="name" :label="$t('finance.billName')" :placeholder="$t('finance.billNamePlaceholder')" />
      <BaseInput v-model="amountText" :label="$t('finance.billAmount')" :placeholder="$t('expenses.amountPlaceholder')" inputmode="decimal" />
      <BaseInput v-model="day" :label="$t('finance.billDay')" inputmode="numeric" />

      <div class="form-field">
        <span class="form-label">{{ $t('expenses.category') }}</span>
        <div class="category-chips">
          <button
            v-for="cat in CATEGORIES"
            :key="cat"
            type="button"
            class="category-chip tap-target"
            :class="{ 'category-chip--active': category === cat }"
            :aria-pressed="category === cat"
            @click="category = category === cat ? null : cat"
          >
            {{ $t(`expenses.categories.${cat}`) }}
          </button>
        </div>
      </div>

      <label class="form-field">
        <span class="form-label">{{ $t('finance.billDefaultPayer') }}</span>
        <select v-model="payerId" class="form-select">
          <option value="">{{ $t('finance.billNoDefaultPayer') }}</option>
          <option v-for="m in expensesStore.members" :key="m.id" :value="m.id">{{ m.display_name }}</option>
        </select>
      </label>

      <label class="active-toggle">
        <input v-model="active" type="checkbox" />
        <span>{{ $t('finance.billActive') }}</span>
      </label>

      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
    </form>
    <template #footer>
      <BaseButton variant="secondary" @click="formOpen = false">{{ $t('common.cancel') }}</BaseButton>
      <BaseButton type="submit" :form="formId" :disabled="!canSubmit" :loading="isPending('bill-form')">
        {{ $t('common.save') }}
      </BaseButton>
    </template>
  </BaseDialog>

  <!-- Löschen bestätigen -->
  <BaseDialog :open="!!deleting" :title="$t('finance.billDeleteTitle')" danger @close="deleting = null">
    <p class="section-sub">{{ $t('finance.billDeleteConfirm', { name: deleting?.name ?? '' }) }}</p>
    <template #footer>
      <BaseButton variant="secondary" @click="deleting = null">{{ $t('common.cancel') }}</BaseButton>
      <BaseButton
        variant="danger"
        :loading="!!deleting && isPending(`bill-delete-${deleting.id}`)"
        @click="confirmDelete"
      >
        {{ $t('common.delete') }}
      </BaseButton>
    </template>
  </BaseDialog>
</template>

<style scoped>
.bills-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.section-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.section-sub {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
}

.manage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.manage-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line);
}

.manage-row:last-child {
  border-bottom: none;
}

.manage-row--paused .manage-row__name {
  color: var(--sub);
}

.manage-row__info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
}

.manage-row__name {
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  overflow-wrap: anywhere;
}

.manage-row__meta {
  font-size: var(--text-sm);
  color: var(--sub);
  overflow-wrap: anywhere;
}

.paused-badge {
  display: inline-block;
  margin-left: var(--space-1);
  padding: var(--badge-padding);
  font-size: var(--text-badge);
  font-weight: var(--font-weight-medium);
  background: var(--chip);
  border-radius: var(--radius-full);
  color: var(--sub);
}

.icon-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--sub);
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--chip);
  color: var(--ink);
}

.icon-btn--danger:hover {
  background: var(--color-danger);
  color: var(--color-on-danger);
}

.bill-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.form-select {
  width: 100%;
  min-height: var(--touch-target);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  font-family: inherit;
  font-size: var(--text-base);
  color: var(--ink);
  background: var(--card);
}

.category-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.category-chip {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-full);
  background: var(--card);
  color: var(--ink);
  font-size: var(--text-sm);
  cursor: pointer;
}

.category-chip--active {
  background: var(--p1);
  border-color: var(--p1);
  color: var(--color-on-primary);
}

.active-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--ink);
  min-height: var(--touch-target);
}

.form-error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}
</style>
