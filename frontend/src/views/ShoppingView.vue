<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useShoppingStore } from '../stores/shopping'
import ShoppingList from '../components/ShoppingList.vue'

const authStore = useAuthStore()
const shoppingStore = useShoppingStore()

onMounted(() => {
  shoppingStore.fetchItems()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">{{ $t('shopping.title') }}</h1>
    <ShoppingList />
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
