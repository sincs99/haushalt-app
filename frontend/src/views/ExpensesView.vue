<script setup lang="ts">
import { onMounted } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import { useSettlementsStore } from '../stores/settlements'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { formatRappen } from '../utils/money'
import { formatDate } from '../utils/dates'
import { X } from 'lucide-vue-next'
import ExpenseList from '../components/ExpenseList.vue'
import BalanceSummary from '../components/BalanceSummary.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'

const expensesStore = useExpensesStore()
const settlementsStore = useSettlementsStore()
const { showToast } = useToast()
const { t } = useI18n()

function resolveUserName(userId: string | null): string {
  if (!userId) return t('common.formerMember')
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.formerMember')
}


async function handleDeleteSettlement(settlementId: string) {
  // Snapshot für Undo
  const settlement = settlementsStore.settlements.find(s => s.id === settlementId)
  if (!settlement) return

  try {
    await settlementsStore.remove(settlementId)
    // Erfolg → Undo-Toast
    showToast(t('common.deleted'), 'success', undefined, {
      label: t('common.undo'),
      onAction: () => {
        // Re-create mit den gleichen Feldern (neue Server-ID ist ok)
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

onMounted(() => {
  expensesStore.fetchExpenses()
  expensesStore.fetchBalances()
  expensesStore.fetchMembers()
  settlementsStore.fetchAll()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">{{ $t('expenses.title') }}</h1>
    <BalanceSummary />
    <ExpenseList />

    <!-- Settlement Skeleton Loading -->
    <BaseCard v-if="settlementsStore.loading && settlementsStore.settlements.length === 0">
      <div class="skeleton-list">
        <div class="skeleton-row" v-for="n in 2" :key="n">
          <BaseSkeleton width="22px" height="22px" rounded />
          <BaseSkeleton width="60%" height="14px" />
          <BaseSkeleton width="80px" height="14px" />
        </div>
      </div>
    </BaseCard>

    <!-- Settlement-Liste -->
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
            <X :size="16" />
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
  display: flex;
  align-items: center;
  gap: var(--space-1);
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

/* Skeleton Loading */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-2);
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
</style>
