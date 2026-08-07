<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useTodosStore } from '../stores/todos'
import TodoList from '../components/TodoList.vue'

const authStore = useAuthStore()
const todosStore = useTodosStore()

onMounted(() => {
  todosStore.fetchTodos()
  todosStore.fetchMembers()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">{{ $t('todos.title') }}</h1>
    <TodoList />
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
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}
</style>
