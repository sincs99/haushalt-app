<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useExpensesStore, apiErrorCode } from '../stores/expenses'
import { useAuthStore } from '../stores/auth'
import { useToast, errorText } from '../composables/useToast'
import { waitForOverlayBack } from '../composables/useBackClose'
import { useI18n } from 'vue-i18n'
import { formatRappen, parseAmountToRappen } from '../utils/money'
import { householdDateString } from '../utils/dates'
import { diffExpense } from '../utils/expenseDiff'
import { validateExpenseShares } from '../utils/expenseShares'
import { expenseToDraft, mergeExpenseDraft, type ExpenseDraft } from '../utils/expenseDraft'
import type { Expense, SplitType } from '../types'
import BaseButton from './ui/BaseButton.vue'
import BaseInput from './ui/BaseInput.vue'
import BaseDialog from './ui/BaseDialog.vue'

const props = defineProps<{
  modelValue: boolean
  expense?: Expense
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const expensesStore = useExpensesStore()
const authStore = useAuthStore()
const { notifySuccess } = useToast()
const formId = `expense-form-${Math.random().toString(36).slice(2, 9)}`
const { t } = useI18n()

// Kategorie-Konstanten
const CATEGORIES = [
  { key: 'groceries', emoji: '🛒' },
  { key: 'housing', emoji: '🏠' },
  { key: 'cats', emoji: '🐈' },
  { key: 'leisure', emoji: '🎮' },
  { key: 'health', emoji: '💊' },
  { key: 'other', emoji: '📦' },
] as const

// Form State
const description = ref('')
const amountText = ref('')
const amountError = ref('')
const expenseDate = ref('')
const paidByUserId = ref('')
const splitType = ref<SplitType>('even')
const selectedCategory = ref<string | null>(null)
const participantIds = ref<string[]>([])
const customShares = ref<Record<string, string>>({})
const serverError = ref('')
const conflictNotice = ref('')
const conflictExpense = ref<Expense | null>(null)
const discardOpen = ref(false)
const initialSnapshot = ref('')
const submitting = ref(false)
/** Basis für Diff + If-Match; erst nach bewusster Konfliktauflösung auf den Serverstand setzen. */
const baseExpense = ref<Expense | null>(null)

// Kategorie-Labels
const categories = computed(() =>
  CATEGORIES.map(c => ({
    ...c,
    label: t(`expenses.categories.${c.key}`),
  }))
)

const isEditMode = computed(() => !!props.expense)
const retroWarning = computed(() => isEditMode.value && !!baseExpense.value?.before_last_settlement)
const dialogTitle = computed(() => isEditMode.value ? t('expenses.editExpense') : t('expenses.newExpense'))

// Betrag parsen
const parsedAmountRappen = computed(() => {
  if (!amountText.value.trim()) return null
  return parseAmountToRappen(amountText.value)
})

// Custom-Shares: Summen-Validierung
const validatedShares = computed(() => validateExpenseShares(customShares.value))
const customSharesSum = computed(() => validatedShares.value.total)

const customSharesValid = computed(() => {
  if (parsedAmountRappen.value === null) return false
  return validatedShares.value.valid && customSharesSum.value === parsedAmountRappen.value
})

// Submit-Validierung
const canSubmit = computed(() => {
  if (conflictExpense.value) return false
  if (!description.value.trim()) return false
  if (parsedAmountRappen.value === null) return false
  if (!paidByUserId.value) return false
  if (splitType.value === 'even' && participantIds.value.length === 0) return false
  if (splitType.value === 'custom' && !customSharesValid.value) return false
  return true
})

// Teilnehmer/Individuell-Felder mit allen Mitgliedern vorbelegen (neue Ausgabe)
function initMemberDefaults() {
  participantIds.value = expensesStore.members.map(m => m.id)
  customShares.value = {}
  for (const m of expensesStore.members) {
    customShares.value[m.id] = ''
  }
  if (!paidByUserId.value && expensesStore.members[0]) {
    paidByUserId.value = expensesStore.members[0].id
  }
}

// Betrag beim Verlassen des Feldes prüfen (nicht erst beim Absenden)
function validateAmount() {
  if (amountText.value.trim() && parsedAmountRappen.value === null) {
    amountError.value = t('expenses.invalidAmount')
  } else {
    amountError.value = ''
  }
}

// Fehler verschwindet, sobald der Betrag wieder gültig ist
watch(amountText, () => {
  if (amountError.value) validateAmount()
})

// Felder aus einer bestehenden Ausgabe füllen
function fillFromExpense(expense: Expense) {
  baseExpense.value = expense
  applyDraft(expenseToDraft(expense))
}

function currentDraft(): ExpenseDraft {
  return {
    description: description.value, amountText: amountText.value,
    expenseDate: expenseDate.value, paidByUserId: paidByUserId.value,
    selectedCategory: selectedCategory.value, splitType: splitType.value,
    participantIds: [...participantIds.value], customShares: { ...customShares.value },
  }
}

function applyDraft(draft: ExpenseDraft) {
  description.value = draft.description
  amountText.value = draft.amountText
  expenseDate.value = draft.expenseDate
  paidByUserId.value = draft.paidByUserId
  selectedCategory.value = draft.selectedCategory
  splitType.value = draft.splitType
  participantIds.value = [...draft.participantIds]
  customShares.value = { ...draft.customShares }
}

const isDirty = computed(() => JSON.stringify(currentDraft()) !== initialSnapshot.value)

function resolveConflict(keepLocal: boolean) {
  const latest = conflictExpense.value
  if (!latest || !baseExpense.value) return
  const latestDraft = expenseToDraft(latest)
  const draft = keepLocal
    ? mergeExpenseDraft(expenseToDraft(baseExpense.value), currentDraft(), latestDraft)
    : latestDraft
  baseExpense.value = latest
  applyDraft(draft)
  initialSnapshot.value = JSON.stringify(latestDraft)
  conflictExpense.value = null
  conflictNotice.value = ''
  validateAmount()
}

// Formular initialisieren/zurücksetzen
function initForm() {
  serverError.value = ''
  conflictNotice.value = ''
  conflictExpense.value = null
  discardOpen.value = false
  amountError.value = ''
  submitting.value = false

  if (props.expense) {
    // Edit-Modus: Felder vorbefüllen
    fillFromExpense(props.expense)
  } else {
    baseExpense.value = null
    // Neuer Eintrag: Defaults
    description.value = ''
    amountText.value = ''
    // Haushaltsdatum (Zeitzone aus /me), sonst lokales Gerätedatum (CASA-39)
    expenseDate.value = householdDateString(authStore.currentHousehold?.timezone)
    paidByUserId.value = authStore.user?.id ?? ''
    splitType.value = 'even'
    selectedCategory.value = null
    initMemberDefaults()
    // Direkt per ?new=1 geöffnet: Mitglieder evtl. noch nicht geladen → nachziehen
    if (expensesStore.members.length === 0) {
      expensesStore.fetchMembers().then(() => {
        if (props.modelValue && !isEditMode.value && participantIds.value.length === 0) {
          const wasDirty = isDirty.value
          initMemberDefaults()
          if (!wasDirty) initialSnapshot.value = JSON.stringify(currentDraft())
        }
      })
    }
  }
  initialSnapshot.value = JSON.stringify(currentDraft())
}

// Watch open-State → Formular initialisieren
watch(() => props.modelValue, (open) => {
  if (open) initForm()
}, { immediate: true })

function close() {
  if (submitting.value) return
  if (isDirty.value) {
    discardOpen.value = true
    return
  }
  dismiss()
}

async function dismiss() {
  const closingConfirmation = discardOpen.value
  discardOpen.value = false
  // The child first restores focus inside this dialog; then the parent restores
  // focus to its original trigger, instead of leaving focus in a removed panel.
  if (closingConfirmation) {
    await nextTick()
    // Child close also starts history.back(). Let its entry disappear before
    // the parent checks/removes its own entry, otherwise a stale depth remains.
    await waitForOverlayBack()
  }
  emit('update:modelValue', false)
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

function resolveUserName(userId: string | null | undefined): string {
  const member = userId ? expensesStore.members.find(m => m.id === userId) : undefined
  return member?.display_name ?? t('common.formerMember')
}

async function handleSubmit() {
  // Doppelt-Senden verhindern (Enter + Klick)
  if (submitting.value) return
  // Betrag validieren
  amountError.value = ''
  serverError.value = ''

  if (parsedAmountRappen.value === null) {
    amountError.value = t('expenses.invalidAmount')
    return
  }
  if (!canSubmit.value) return

  // Ohne Netz gar nicht erst senden — Eingaben bleiben erhalten
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    serverError.value = t('offline.actionBlocked')
    return
  }

  submitting.value = true

  try {
    if (isEditMode.value && baseExpense.value) {
      // Edit: nur geänderte Felder senden, mit Version (If-Match) — ein älterer Dialog
      // überschreibt so keine Korrektur eines anderen Mitglieds (CASA-09, PD-F7)
      const base = baseExpense.value
      const payload = diffExpense(base, {
        description: description.value,
        amount_rappen: parsedAmountRappen.value,
        paid_by_user_id: paidByUserId.value,
        expense_date: expenseDate.value,
        category: selectedCategory.value,
        split_type: splitType.value,
        participant_ids: participantIds.value,
        shares: splitType.value === 'custom' ? validatedShares.value.shares : [],
      })
      if (Object.keys(payload).length === 0) {
        dismiss()
        return
      }
      await expensesStore.editExpense(base.id, payload, base.version)
    } else {
      // Create
      const shares = splitType.value === 'custom' ? validatedShares.value.shares : []

      await expensesStore.addExpense({
        description: description.value.trim(),
        amount_rappen: parsedAmountRappen.value,
        paid_by_user_id: paidByUserId.value,
        expense_date: expenseDate.value,
        split_type: splitType.value,
        category: selectedCategory.value || undefined,
        ...(splitType.value === 'even'
          ? { participant_ids: participantIds.value }
          : { shares }),
      })
    }
    dismiss()
    // Neue Ausgabe liegt auf dem Handy oft unter dem Falz → kurze Bestätigung
    notifySuccess(t('expenses.saved'))
  } catch (e: any) {
    const code = apiErrorCode(e)
    if (code === 'EXPENSE_VERSION_CONFLICT') {
      // Keep both versions until the user explicitly chooses how to resolve the conflict.
      const current = e.response.data.detail.current as Expense | undefined
      const fresh = current ?? (await expensesStore.refreshExpense(baseExpense.value!.id).catch(() => undefined))
      conflictExpense.value = fresh ?? null
      conflictNotice.value = fresh
        ? t('expenses.conflictPreserved', { name: resolveUserName(fresh.updated_by_user_id) })
        : t('expenses.conflictRefreshFailed')
    } else if (code === 'EXPENSE_DELETED') {
      serverError.value = t('expenses.deletedMeanwhile')
    } else {
      // Übersetzter Fehlercode statt rohem (oft englischem) detail
      serverError.value = errorText(t('expenses.submitError'), e)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <BaseDialog :open="modelValue" :title="dialogTitle" @close="close">
    <form :id="formId" class="dialog-form" novalidate @submit.prevent="handleSubmit">
      <!-- Bereits ausgeglichen: Änderungen verschieben Salden nachträglich (PD-F2) -->
      <p v-if="retroWarning" class="retro-warning" role="note">{{ $t('expenses.retroWarning') }}</p>
      <p v-if="conflictNotice" class="conflict-notice" role="alert">{{ conflictNotice }}</p>
      <section v-if="conflictExpense" class="conflict-details" :aria-label="$t('expenses.conflictLatest')">
        <h3>{{ $t('expenses.conflictLatest') }}</h3>
        <dl>
          <dt>{{ $t('expenses.description') }}</dt><dd>{{ conflictExpense.description }}</dd>
          <dt>{{ $t('expenses.amount') }}</dt><dd>{{ formatRappen(conflictExpense.amount_rappen) }}</dd>
          <dt>{{ $t('expenses.date') }}</dt><dd>{{ conflictExpense.expense_date }}</dd>
          <dt>{{ $t('expenses.payer') }}</dt><dd>{{ resolveUserName(conflictExpense.paid_by_user_id) }}</dd>
          <dt>{{ $t('expenses.category') }}</dt><dd>{{ conflictExpense.category ? $t(`expenses.categories.${conflictExpense.category}`) : '—' }}</dd>
          <dt>{{ $t('expenses.splitType') }}</dt><dd>{{ $t(conflictExpense.split_type === 'even' ? 'expenses.splitEven' : 'expenses.splitCustom') }}</dd>
        </dl>
        <ul>
          <li v-for="share in conflictExpense.shares" :key="share.user_id">
            {{ resolveUserName(share.user_id) }}: {{ formatRappen(share.amount_rappen) }}
          </li>
        </ul>
        <p>{{ $t('expenses.conflictOverwriteHint') }}</p>
        <div class="conflict-actions">
          <BaseButton type="button" variant="secondary" @click="resolveConflict(true)">{{ $t('expenses.conflictKeepMine') }}</BaseButton>
          <BaseButton type="button" variant="secondary" @click="resolveConflict(false)">{{ $t('expenses.conflictUseLatest') }}</BaseButton>
        </div>
      </section>

      <!-- Beschreibung -->
      <BaseInput
        v-model="description"
        :label="$t('expenses.description')"
        :placeholder="$t('expenses.descriptionPlaceholder')"
        :error="description.trim().length === 0 && description.length > 0 ? $t('expenses.descriptionRequired') : undefined"
      />

      <!-- Betrag -->
      <BaseInput
        v-model="amountText"
        :label="$t('expenses.amount')"
        :placeholder="$t('expenses.amountPlaceholder')"
        inputmode="decimal"
        :error="amountError || undefined"
        @blur="validateAmount"
      />

      <!-- Datum -->
      <div class="form-field">
        <label class="form-field__label" for="expense-date">{{ $t('expenses.date') }}</label>
        <input
          id="expense-date"
          v-model="expenseDate"
          type="date"
          class="form-field__input"
        />
      </div>

      <!-- Kategorie -->
      <div class="form-field">
        <label class="form-field__label">{{ $t('expenses.category') }}</label>
        <div class="category-chips">
          <button
            v-for="cat in categories"
            :key="cat.key"
            type="button"
            class="category-chip tap-target"
            :class="{ 'category-chip--active': selectedCategory === cat.key }"
            @click="selectedCategory = selectedCategory === cat.key ? null : cat.key"
          >
            {{ cat.emoji }} {{ cat.label }}
          </button>
        </div>
      </div>

      <!-- Bezahlt von -->
      <div class="form-field">
        <label class="form-field__label" for="expense-paid-by">{{ $t('expenses.payer') }}</label>
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
        <label class="form-field__label">{{ $t('expenses.splitType') }}</label>
        <div class="split-toggle">
          <button
            type="button"
            class="split-toggle__btn"
            :class="{ 'split-toggle__btn--active': splitType === 'even' }"
            @click="splitType = 'even'"
          >
            {{ $t('expenses.splitEven') }}
          </button>
          <button
            type="button"
            class="split-toggle__btn"
            :class="{ 'split-toggle__btn--active': splitType === 'custom' }"
            @click="splitType = 'custom'"
          >
            {{ $t('expenses.splitCustom') }}
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
        <p :id="`${formId}-share-hint`" class="custom-shares__hint">{{ $t('expenses.customSplit.zeroHint') }}</p>
        <div
          v-for="member in expensesStore.members"
          :key="member.id"
          class="custom-share-row"
        >
          <label :for="`${formId}-share-${member.id}`" class="custom-share-row__name">{{ member.display_name }}</label>
          <input
            :id="`${formId}-share-${member.id}`"
            v-model="customShares[member.id]"
            class="custom-share-row__input"
            inputmode="decimal"
            placeholder="0.00"
            :aria-invalid="validatedShares.invalidIds.includes(member.id)"
            :aria-describedby="validatedShares.invalidIds.includes(member.id) ? `${formId}-share-error-${member.id}` : `${formId}-share-hint`"
          />
          <p v-if="validatedShares.invalidIds.includes(member.id)" :id="`${formId}-share-error-${member.id}`" class="custom-share-row__error" role="alert">
            {{ $t('expenses.customSplit.invalidShare') }}
          </p>
        </div>
        <div class="custom-shares__summary">
          <span>{{ $t('expenses.customSplit.allocated') }}: {{ formatRappen(customSharesSum) }}</span>
          <span v-if="parsedAmountRappen !== null"> / {{ formatRappen(parsedAmountRappen) }}</span>
          <span
            v-if="parsedAmountRappen !== null && customSharesSum !== parsedAmountRappen"
            class="custom-shares__warning"
          >
            ≠ {{ $t('expenses.customSplit.mismatch') }}
          </span>
        </div>
      </div>

      <!-- Wer hat erfasst / zuletzt geändert (PD-F1) -->
      <p v-if="isEditMode && baseExpense" class="expense-audit">
        <span v-if="baseExpense.created_by_user_id">
          {{ $t('expenses.createdBy', { name: resolveUserName(baseExpense.created_by_user_id) }) }}
        </span>
        <span v-if="baseExpense.updated_by_user_id">
          {{ $t('expenses.updatedBy', { name: resolveUserName(baseExpense.updated_by_user_id) }) }}
        </span>
      </p>

      <!-- Server-Fehler -->
      <p v-if="serverError" class="server-error" role="alert">{{ serverError }}</p>
    </form>

    <template #footer>
      <BaseButton type="button" variant="secondary" :disabled="submitting" @click="close">
        {{ $t('common.cancel') }}
      </BaseButton>
      <BaseButton
        type="submit"
        :form="formId"
        variant="primary"
        :disabled="!canSubmit"
        :loading="submitting"
      >
        {{ isEditMode ? $t('expenses.saveExpense') : $t('common.add') }}
      </BaseButton>
    </template>
  </BaseDialog>
  <BaseDialog :open="modelValue && discardOpen" :title="$t('expenses.discardTitle')" @close="discardOpen = false">
    <p>{{ $t('expenses.discardMessage') }}</p>
    <template #footer>
      <BaseButton type="button" variant="secondary" @click="discardOpen = false">{{ $t('expenses.keepEditing') }}</BaseButton>
      <BaseButton type="button" variant="danger" @click="dismiss">{{ $t('expenses.discard') }}</BaseButton>
    </template>
  </BaseDialog>
</template>

<style scoped>
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
  border: 1px solid var(--line-strong);
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
  border: 1px solid var(--line-strong);
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
  border-right: 1px solid var(--line-strong);
}

.split-toggle__btn--active {
  background: var(--color-primary);
  color: var(--color-on-primary);
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
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.custom-shares__hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.custom-share-row__error {
  flex-basis: 100%;
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.custom-share-row__input[aria-invalid="true"] {
  border-color: var(--color-danger);
}

.conflict-details {
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

.conflict-details h3 { margin-top: 0; }
.conflict-details dt { font-weight: var(--font-weight-medium); }
.conflict-details dd { margin: 0 0 var(--space-2); }
.conflict-details ul { padding-left: var(--space-4); }
.conflict-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }

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
  border: 1px solid var(--line-strong);
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

/* Hinweise: nachträgliche Saldo-Änderung, inzwischen geändert */
.retro-warning,
.conflict-notice {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-warning-soft);
  border-radius: var(--radius-sm);
  color: var(--color-warning-strong);
  font-size: var(--text-sm);
}

.expense-audit {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  color: var(--sub);
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


/* ── Kategorie-Chips ── */
.category-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.category-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-full);
  background: var(--card);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
  color: var(--ink);
  font-family: var(--font-family);
}

.category-chip:hover {
  border-color: var(--p1);
}

.category-chip--active {
  background: var(--p1);
  color: var(--color-on-primary);
  border-color: var(--p1);
}
</style>
