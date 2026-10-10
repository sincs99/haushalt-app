<script setup lang="ts">
/**
 * Verlauf gelöschter Ausgaben und Ausgleiche (PD-F1): „gelöscht von X am …“ und
 * Wiederherstellen. Wird erst beim Aufklappen geladen.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useExpensesStore } from '../stores/expenses'
import { useSettlementsStore } from '../stores/settlements'
import { useAsyncAction } from '../composables/useAsyncAction'
import { formatRappen } from '../utils/money'
import { formatDate } from '../utils/dates'
import { PhArrowCounterClockwise } from '@phosphor-icons/vue'
import BaseCard from './ui/BaseCard.vue'
import BaseErrorState from './ui/BaseErrorState.vue'
import BaseSkeleton from './ui/BaseSkeleton.vue'

const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const open = ref(false)
const loading = ref(false)
const loadError = ref(false)

interface HistoryEntry {
  kind: 'expense' | 'settlement'
  id: string
  title: string
  amount: number
  date: string
  deletedAt: string
  deletedBy: string | null | undefined
}

function userName(userId: string | null | undefined): string {
  const member = userId ? expensesStore.members.find(m => m.id === userId) : undefined
  return member?.display_name ?? t('common.formerMember')
}

const entries = computed<HistoryEntry[]>(() => {
  const list: HistoryEntry[] = [
    ...expensesStore.deletedExpenses.map(e => ({
      kind: 'expense' as const,
      id: e.id,
      title: e.description,
      amount: e.amount_rappen,
      date: e.expense_date,
      deletedAt: e.deleted_at ?? '',
      deletedBy: e.deleted_by_user_id,
    })),
    ...settlementsStore.deletedSettlements.map(s => ({
      kind: 'settlement' as const,
      id: s.id,
      title: t('expenses.history.settlementName', { from: userName(s.from_user_id), to: userName(s.to_user_id) }),
      amount: s.amount_rappen,
      date: s.settled_date,
      deletedAt: s.deleted_at ?? '',
      deletedBy: s.deleted_by_user_id,
    })),
  ]
  return list.sort((a, b) => (a.deletedAt < b.deletedAt ? 1 : -1))
})

async function load() {
  loading.value = true
  loadError.value = false
  try {
    await Promise.all([expensesStore.fetchDeleted(), settlementsStore.fetchDeleted()])
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) load()
}

async function restore(entry: HistoryEntry) {
  await run<unknown>(
    () => entry.kind === 'expense' ? expensesStore.restoreExpense(entry.id) : settlementsStore.restore(entry.id),
    {
      key: `restore-${entry.id}`,
      success: t('expenses.history.restored'),
      error: t('expenses.history.restoreError'),
    },
  )
}
</script>

<template>
  <div class="history">
    <button type="button" class="history__toggle" :aria-expanded="open" @click="toggle">
      {{ open ? $t('expenses.history.hide') : $t('expenses.history.show') }}
    </button>

    <BaseCard v-if="open" padding="md">
      <h2 class="section-title">{{ $t('expenses.history.title') }}</h2>

      <div v-if="loading && entries.length === 0" class="history__skeleton">
        <BaseSkeleton v-for="n in 2" :key="n" width="100%" height="36px" />
      </div>
      <BaseErrorState v-else-if="loadError" :message="$t('expenses.history.loadError')" :retrying="loading" @retry="load" />
      <p v-else-if="entries.length === 0" class="section-sub">{{ $t('expenses.history.empty') }}</p>

      <ul v-else class="history__list">
        <li v-for="entry in entries" :key="entry.kind + entry.id" class="history__row">
          <div class="history__info">
            <span class="history__title">{{ entry.title }}</span>
            <span class="history__meta">
              {{ formatRappen(entry.amount) }} · {{ formatDate(entry.date) }}
            </span>
            <span class="history__meta">
              {{ $t('expenses.history.deletedBy', { name: userName(entry.deletedBy), date: entry.deletedAt ? formatDate(entry.deletedAt) : '' }) }}
            </span>
          </div>
          <button
            type="button"
            class="history__restore tap-target"
            :disabled="isPending(`restore-${entry.id}`)"
            :title="$t('expenses.history.restore')"
            :aria-label="$t('expenses.history.restoreLabel', { name: entry.title })"
            @click="restore(entry)"
          >
            <PhArrowCounterClockwise :size="16" />
            <span>{{ $t('expenses.history.restore') }}</span>
          </button>
        </li>
      </ul>
    </BaseCard>
  </div>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.history__toggle {
  align-self: flex-start;
  background: none;
  border: none;
  padding: var(--space-2) 0;
  min-height: var(--touch-target);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--p1);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.section-title {
  margin: 0 0 var(--space-3) 0;
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

.history__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.history__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.history__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line);
}

.history__row:last-child {
  border-bottom: none;
}

.history__info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
}

.history__title {
  color: var(--sub);
  text-decoration: line-through;
  overflow-wrap: anywhere;
}

.history__meta {
  font-size: var(--text-xs);
  color: var(--sub);
}

.history__restore {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  background: var(--card);
  color: var(--ink);
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  cursor: pointer;
}

.history__restore:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
