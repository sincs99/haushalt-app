<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useTodosStore } from '../stores/todos'
import { useSocket } from '../composables/useSocket'
import { useLoader } from '../composables/useLoader'

import PageHeader from '../components/ui/PageHeader.vue'
import BasePillTabs from '../components/ui/BasePillTabs.vue'
import TodoList from '../components/TodoList.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const socket = useSocket()

const todosStore = useTodosStore()

// Laden mit Fehlerzustand („Erneut versuchen“ statt „Keine offenen Aufgaben“)
const { loadError, reloading, reload } = useLoader(() =>
  Promise.all([todosStore.fetchTodos(), todosStore.fetchMembers()]),
)

// ── Filter State ──
const activeFilter = ref('all')

// ── Filter Tabs (Alle / pro Mitglied) ──
const filterTabs = computed(() => {
  const tabs: Array<{ key: string; label: string }> = [
    { key: 'all', label: t('tasks.filterAll') },
  ]

  for (const member of todosStore.members) {
    const count = todosStore.items.filter(
      (item) => item.assigned_to_user_id === member.id && !item.is_done,
    ).length
    const name = member.display_name.split(' ')[0]
    tabs.push({
      key: member.id,
      label: count > 0 ? `${name} (${count})` : name,
    })
  }

  return tabs
})

// ── Filter Value für TodoList-Prop ──
const filterUserId = computed<string | undefined>(() => {
  if (activeFilter.value === 'all') return undefined
  return activeFilter.value
})

const filterUserName = computed(() =>
  todosStore.members.find((m) => m.id === filterUserId.value)?.display_name.split(' ')[0],
)

const openCount = computed(() => todosStore.items.filter((i) => !i.is_done).length)

// ── Auto-Focus wenn ?new=1 ──
const shouldAutoFocus = computed(() => route.query.new === '1')

// ── Socket ──
// Einzelne todo_*-Events verarbeitet der Store (in App.vue registriert) per
// Merge — kein Komplett-Refetch, der laufende optimistische Änderungen überschreibt.
// Nur nach einem Reconnect alles neu laden (verpasste Events).
function handleReconnect() {
  todosStore.fetchTodos().catch(() => {})
}

// ── Lifecycle ──
onMounted(() => {
  reload()

  // ?new=1 Query-Param entfernen nach dem Lesen
  if (route.query.new === '1') {
    router.replace({ query: {} })
  }

  socket.onReconnect(handleReconnect)
})

onUnmounted(() => {
  socket.offReconnect(handleReconnect)
})
</script>

<template>
  <div class="view-page">
    <!-- Segment Control: Aufgaben | Ämtli -->
    <div class="segment-control">
      <router-link to="/todos" :class="{ active: route.path === '/todos' }">
        {{ $t('tasks.segmentTodos') }}
      </router-link>
      <router-link to="/chores" :class="{ active: route.path === '/chores' }">
        {{ $t('tasks.segmentChores') }}
      </router-link>
    </div>

    <PageHeader
      :title="$t('tasks.title')"
      :subtitle="openCount > 0 ? $t('tasks.openCount', { n: openCount }) : undefined"
    />

    <!-- Person Filter Pills -->
    <BasePillTabs
      :tabs="filterTabs"
      v-model="activeFilter"
    />

    <!-- TodoList Komponente (Herzstück) -->
    <TodoList
      :filter-user-id="filterUserId"
      :filter-user-name="filterUserName"
      :auto-focus="shouldAutoFocus"
      :load-error="loadError"
      :retrying="reloading"
      @retry="reload"
    />
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Segment Control ── */
.segment-control {
  display: flex;
  background: var(--chip);
  border-radius: var(--radius-btn);
  padding: 3px;
  gap: 2px;
}

.segment-control a {
  flex: 1;
  text-align: center;
  padding: var(--space-2) var(--space-3);
  border-radius: calc(var(--radius-btn) - 2px);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--sub);
  text-decoration: none;
  transition: all var(--transition-fast);
}

.segment-control a.active {
  background: var(--card);
  color: var(--ink);
  box-shadow: var(--shadow-sm);
}
</style>
