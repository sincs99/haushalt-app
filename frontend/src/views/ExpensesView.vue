<script setup lang="ts">
import { onMounted } from 'vue'
import { useExpensesStore } from '../stores/expenses'
import ExpenseList from '../components/ExpenseList.vue'
import BalanceSummary from '../components/BalanceSummary.vue'

const expensesStore = useExpensesStore()

onMounted(() => {
  expensesStore.fetchExpenses()
  expensesStore.fetchBalances()
  expensesStore.fetchMembers()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">💰 Ausgaben</h1>
    <BalanceSummary />
    <ExpenseList />
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
</style>
