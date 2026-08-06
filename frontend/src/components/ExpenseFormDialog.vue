<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import { formatRappen, parseAmountToRappen } from '../utils/money'
import type { Expense, SplitType, ExpenseShare } from '../types'
import BaseButton from './ui/BaseButton.vue'
import BaseInput from './ui/BaseInput.vue'

const props = defineProps<{
  modelValue: boolean
  expense?: Expense
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const expensesStore = useExpensesStore()
const authStore = useAuthStore()
const { showToast } = useToast()

// Form State
const description = ref('')
const amountText = ref('')
const amountError = ref('')
const expenseDate = ref('')
const paidByUserId = ref('')
const splitType = ref<SplitType>('even')
const participantIds = ref<string[]>([])
const customShares = ref<Record<string, string>>({})
const serverError = ref('')
const submitting = ref(false)

const isEditMode = computed(() => !!props.expense)
const dialogTitle = computed(() => isEditMode.value ? 'Ausgabe bearbeiten' : 'Neue Ausgabe')

// Betrag parsen
const parsedAmountRappen = computed(() => {
  if (!amountText.value.trim()) return null
  return parseAmountToRappen(amountText.value)
})

// Custom-Shares: Summen-Validierung
const customSharesSum = computed(() => {
  let sum = 0
  for (const memberId of Object.keys(customShares.value)) {
    const parsed = parseAmountToRappen(customShares.value[memberId])
    if (parsed !== null) sum += parsed
  }
  return sum
})

const customSharesValid = computed(() => {
  if (parsedAmountRappen.value === null) return false
  return customSharesSum.value === parsedAmountRappen.value
})

// Submit-Validierung
const canSubmit = computed(() => {
  if (!description.value.trim()) return false
  if (parsedAmountRappen.value === null) return false
  if (!paidByUserId.value) return false
  if (splitType.value === 'even' && participantIds.value.length === 0) return false
  if (splitType.value === 'custom' && !customSharesValid.value) return false
  return true
})

// Formular initialisieren/zurücksetzen
function initForm() {
  serverError.value = ''
  amountError.value = ''
  submitting.value = false

  if (props.expense) {
    // Edit-Modus: Felder vorbefüllen
    description.value = props.expense.description
    amountText.value = (props.expense.amount_rappen / 100).toFixed(2)
    expenseDate.value = props.expense.expense_date
    paidByUserId.value = props.expense.paid_by_user_id ?? ''
    // Backend speichert keinen split_type — immer als "custom" anzeigen mit bestehenden Share-Beträgen
    splitType.value = 'custom'
    customShares.value = {}
    for (const share of props.expense.shares) {
      customShares.value[share.user_id] = (share.amount_rappen / 100).toFixed(2)
    }
    participantIds.value = props.expense.shares.map(s => s.user_id)
  } else {
    // Neuer Eintrag: Defaults
    description.value = ''
    amountText.value = ''
    expenseDate.value = new Date().toISOString().slice(0, 10)
    paidByUserId.value = authStore.user?.id ?? ''
    splitType.value = 'even'
    participantIds.value = expensesStore.members.map(m => m.id)
    customShares.value = {}
    for (const m of expensesStore.members) {
      customShares.value[m.id] = ''
    }
  }
}

// Watch open-State → Formular initialisieren
watch(() => props.modelValue, (open) => {
  if (open) initForm()
})

function close() {
  emit('update:modelValue', false)
}

function handleOverlayClick(e: MouseEvent) {
  if (e.target === e.currentTarget) close()
}

function toggleParticipant(memberId: string) {
  const idx = participantIds.value.indexOf(memberId)
  if (idx !== -1) {
    // Mindestens 1 muss gewählt bleiben
    if (participantIds.value.length > 1) {
      participantIds.value.splice(idx, 1)
    }
  } else {
    participantIds.value.push(memberId)
  }
}

function resolveUserName(userId: string): string {
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? 'Ehemaliges Mitglied'
}

async function handleSubmit() {
  // Betrag validieren
  amountError.value = ''
  serverError.value = ''

  if (parsedAmountRappen.value === null) {
    amountError.value = 'Ungültiger Betrag'
    return
  }

  submitting.value = true

  try {
    if (isEditMode.value && props.expense) {
      // Edit
      const shares: ExpenseShare[] = []
      if (splitType.value === 'custom') {
        for (const memberId of Object.keys(customShares.value)) {
          const parsed = parseAmountToRappen(customShares.value[memberId])
          if (parsed !== null && parsed > 0) {
            shares.push({ user_id: memberId, amount_rappen: parsed })
          }
        }
      }

      await expensesStore.editExpense(props.expense.id, {
        description: description.value.trim(),
        amount_rappen: parsedAmountRappen.value,
        paid_by_user_id: paidByUserId.value,
        expense_date: expenseDate.value,
        split_type: splitType.value,
        ...(splitType.value === 'even'
          ? { participant_ids: participantIds.value }
          : { shares }),
      })
    } else {
      // Create
      const shares: ExpenseShare[] = []
      if (splitType.value === 'custom') {
        for (const memberId of Object.keys(customShares.value)) {
          const parsed = parseAmountToRappen(customShares.value[memberId])
          if (parsed !== null && parsed > 0) {
            shares.push({ user_id: memberId, amount_rappen: parsed })
          }
        }
      }

      await expensesStore.addExpense({
        description: description.value.trim(),
        amount_rappen: parsedAmountRappen.value,
        paid_by_user_id: paidByUserId.value,
        expense_date: expenseDate.value,
        split_type: splitType.value,
        ...(splitType.value === 'even'
          ? { participant_ids: participantIds.value }
          : { shares }),
      })
    }
    close()
  } catch (e: any) {
    const detail = e.response?.data?.detail
    if (typeof detail === 'string') {
      serverError.value = detail
    } else if (Array.isArray(detail)) {
      serverError.value = detail.map((d: any) => d.msg ?? d).join(', ')
    } else {
      serverError.value = e.message || 'Ein Fehler ist aufgetreten'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="dialog-overlay" @click="handleOverlayClick">
      <div class="dialog-content" role="dialog" aria-modal="true">
        <h2 class="dialog-title">{{ dialogTitle }}</h2>

        <form class="dialog-form" @submit.prevent="handleSubmit">
          <!-- Beschreibung -->
          <BaseInput
            v-model="description"
            label="Beschreibung"
            placeholder="z.B. Einkauf Migros"
            :error="description.trim().length === 0 && description.length > 0 ? 'Beschreibung erforderlich' : undefined"
          />

          <!-- Betrag -->
          <BaseInput
            v-model="amountText"
            label="Betrag (CHF)"
            placeholder="z.B. 23.50"
            inputmode="decimal"
            :error="amountError || undefined"
          />

          <!-- Datum -->
          <div class="form-field">
            <label class="form-field__label" for="expense-date">Datum</label>
            <input
              id="expense-date"
              v-model="expenseDate"
              type="date"
              class="form-field__input"
            />
          </div>

          <!-- Bezahlt von -->
          <div class="form-field">
            <label class="form-field__label" for="expense-paid-by">Bezahlt von</label>
            <select
              id="expense-paid-by"
              v-model="paidByUserId"
              class="form-field__input"
            >
              <option v-for="member in expensesStore.members" :key="member.id" :value="member.id">
                {{ member.display_name }}
              </option>
            </select>
          </div>

          <!-- Split-Typ Auswahl -->
          <div class="form-field">
            <label class="form-field__label">Aufteilung</label>
            <div class="split-toggle">
              <button
                type="button"
                class="split-toggle__btn"
                :class="{ 'split-toggle__btn--active': splitType === 'even' }"
                @click="splitType = 'even'"
              >
                Gleichmässig
              </button>
              <button
                type="button"
                class="split-toggle__btn"
                :class="{ 'split-toggle__btn--active': splitType === 'custom' }"
                @click="splitType = 'custom'"
              >
                Individuell
              </button>
            </div>
          </div>

          <!-- Gleichmässig: Teilnehmer-Checkboxen -->
          <div v-if="splitType === 'even'" class="participants">
            <label
              v-for="member in expensesStore.members"
              :key="member.id"
              class="participant-check"
            >
              <input
                type="checkbox"
                :checked="participantIds.includes(member.id)"
                @change="toggleParticipant(member.id)"
                class="participant-check__input"
              />
              <span class="participant-check__name">{{ member.display_name }}</span>
            </label>
          </div>

          <!-- Individuell: Betrags-Felder pro Mitglied -->
          <div v-if="splitType === 'custom'" class="custom-shares">
            <div
              v-for="member in expensesStore.members"
              :key="member.id"
              class="custom-share-row"
            >
              <span class="custom-share-row__name">{{ member.display_name }}</span>
              <input
                v-model="customShares[member.id]"
                class="custom-share-row__input"
                inputmode="decimal"
                placeholder="0.00"
              />
            </div>
            <div class="custom-shares__summary">
              <span>Aufgeteilt: {{ formatRappen(customSharesSum) }}</span>
              <span v-if="parsedAmountRappen !== null"> / {{ formatRappen(parsedAmountRappen) }}</span>
              <span
                v-if="parsedAmountRappen !== null && customSharesSum !== parsedAmountRappen"
                class="custom-shares__warning"
              >
                ≠ Summe stimmt nicht
              </span>
            </div>
          </div>

          <!-- Server-Fehler -->
          <p v-if="serverError" class="server-error">{{ serverError }}</p>

          <!-- Aktionen -->
          <div class="dialog-actions">
            <BaseButton
              type="submit"
              variant="primary"
              :disabled="!canSubmit"
              :loading="submitting"
            >
              {{ isEditMode ? 'Speichern' : 'Hinzufügen' }}
            </BaseButton>
            <BaseButton type="button" variant="secondary" @click="close">
              Abbrechen
            </BaseButton>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
}

.dialog-content {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--shadow-overlay);
}

.dialog-title {
  margin: 0 0 var(--space-4) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Native Inputs (date, select) — gleiches Styling wie BaseInput */
.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-field__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
}

.form-field__input {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-size: var(--text-base);
  line-height: var(--line-height-normal);
  color: var(--color-text);
  background-color: var(--color-surface);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.form-field__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* Split-Toggle (Segmented) */
.split-toggle {
  display: flex;
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.split-toggle__btn {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-family: var(--font-family);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  min-height: 44px;
}

.split-toggle__btn:not(:last-child) {
  border-right: 1px solid var(--color-neutral-300);
}

.split-toggle__btn--active {
  background: var(--color-primary);
  color: var(--color-surface);
}

/* Teilnehmer-Checkboxen */
.participants {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.participant-check {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  cursor: pointer;
  min-height: 44px;
}

.participant-check__input {
  width: 20px;
  height: 20px;
  accent-color: var(--color-primary);
  cursor: pointer;
  flex-shrink: 0;
}

.participant-check__name {
  font-size: var(--text-base);
  color: var(--color-text);
}

/* Custom Shares */
.custom-shares {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.custom-share-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.custom-share-row__name {
  flex: 1;
  font-size: var(--text-base);
  color: var(--color-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.custom-share-row__input {
  width: 100px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-size: var(--text-base);
  color: var(--color-text);
  background: var(--color-surface);
  text-align: right;
}

.custom-share-row__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.custom-shares__summary {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  padding-top: var(--space-1);
}

.custom-shares__warning {
  color: var(--color-danger);
  font-weight: var(--font-weight-medium);
  margin-left: var(--space-2);
}

/* Server-Fehler */
.server-error {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-danger-light);
  border-radius: var(--radius-sm);
  color: var(--color-danger);
  font-size: var(--text-sm);
}

/* Aktionen */
.dialog-actions {
  display: flex;
  gap: var(--space-3);
}

.dialog-actions > * {
  flex: 1;
}
</style>
