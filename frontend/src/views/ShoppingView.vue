<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useShoppingStore } from '../stores/shopping'
import { useI18n } from 'vue-i18n'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import ShoppingList from '../components/ShoppingList.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import { PhPlus, PhShoppingCart, PhDotsThreeVertical } from '@phosphor-icons/vue'

const route = useRoute()
const router = useRouter()
const shoppingStore = useShoppingStore()
const { t } = useI18n()
const { run, isPending } = useAsyncAction()

const autoFocus = computed(() => route.query.new === '1')

// Listen und Artikel parallel laden; Fehler → „Erneut versuchen“ statt Leerzustand
const loadedOnce = ref(false)
const { loadError, reloading, reload } = useLoader(async () => {
  try {
    await Promise.all([shoppingStore.fetchLists(), shoppingStore.fetchItems()])
  } finally {
    loadedOnce.value = true
  }
})

// Listen-Pills — open_count lokal berechnen statt Server-Wert (wird stale)
const listTabs = computed(() => {
  return shoppingStore.lists.map(l => {
    const openCount = shoppingStore.items.filter(
      i => i.list_id === l.id && !i.is_checked,
    ).length
    return {
      key: l.id,
      label: `${l.name} (${openCount})`,
    }
  })
})

const activeTab = computed({
  get: () => shoppingStore.activeListId ?? '',
  set: (val: string) => shoppingStore.setActiveList(val),
})

// Neue-Liste-Dialog
const showNewListDialog = ref(false)
const newListName = ref('')

async function handleCreateList() {
  const name = newListName.value.trim()
  if (!name) return
  const ok = await run(async () => {
    const created = await shoppingStore.createList(name)
    // Neue Liste gleich auswählen (bei der ersten Liste bliebe die Seite sonst leer)
    if (created) shoppingStore.setActiveList(created.id)
  }, { key: 'createList', error: t('shopping.createListError') })
  if (ok) {
    newListName.value = ''
    showNewListDialog.value = false
  }
}

// ── Liste bearbeiten (umbenennen / löschen) ──
const activeList = computed(() =>
  shoppingStore.lists.find(l => l.id === shoppingStore.activeListId) ?? null,
)
const showEditListDialog = ref(false)
const editListName = ref('')
const confirmingListDelete = ref(false)

const activeListItemCount = computed(() =>
  shoppingStore.items.filter(i => i.list_id === shoppingStore.activeListId).length,
)

function openEditList() {
  if (!activeList.value) return
  editListName.value = activeList.value.name
  confirmingListDelete.value = false
  showEditListDialog.value = true
}

async function handleRenameList() {
  const list = activeList.value
  const name = editListName.value.trim()
  if (!list || !name) return
  if (name === list.name) {
    showEditListDialog.value = false
    return
  }
  const ok = await run(() => shoppingStore.updateList(list.id, { name }), {
    key: 'editList',
    error: t('shopping.updateListError'),
  })
  if (ok) showEditListDialog.value = false
}

async function handleDeleteList() {
  const list = activeList.value
  if (!list) return
  // Erster Klick: Bestätigung im Dialog anzeigen
  if (!confirmingListDelete.value) {
    confirmingListDelete.value = true
    return
  }
  const ok = await run(
    () => shoppingStore.deleteList(list.id, activeListItemCount.value > 0),
    { key: 'editList', success: t('shopping.listDeleted'), error: t('shopping.deleteListError') },
  )
  if (ok) showEditListDialog.value = false
}

// Gesamtzahl offener Items über alle Listen — lokal berechnet
const totalOpenCount = computed(() =>
  shoppingStore.items.filter(i => !i.is_checked).length,
)

onMounted(async () => {
  await reload()
  // ?list=<id> kommt von einem Einkaufslisten-Tag (NFC/QR)
  const listId = typeof route.query.list === 'string' ? route.query.list : null
  if (listId && shoppingStore.lists.some(l => l.id === listId)) {
    shoppingStore.setActiveList(listId)
  }
  if (route.query.new === '1' || listId) {
    router.replace({ query: {} })
  }
})
</script>

<template>
  <div class="view-page">
    <PageHeader
      :title="$t('shopping.title')"
      :subtitle="totalOpenCount > 0 ? $t('shopping.openCount', { n: totalOpenCount }) : undefined"
    />

    <!-- Listen-Pills (immer sichtbar, enthält mindestens den „+"-Button) -->
    <div class="list-pills">
      <template v-for="tab in listTabs" :key="tab.key">
        <button
          type="button"
          class="pill-tab"
          :class="{ 'pill-tab--active': activeTab === tab.key }"
          :aria-pressed="activeTab === tab.key"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
        <!-- Aktionen für die aktive Liste (umbenennen / löschen) -->
        <button
          v-if="activeTab === tab.key"
          type="button"
          class="pill-tab pill-tab--add"
          :aria-label="$t('shopping.editList')"
          :title="$t('shopping.editList')"
          @click="openEditList"
        >
          <PhDotsThreeVertical :size="16" weight="bold" />
        </button>
      </template>
      <button
        type="button"
        class="pill-tab pill-tab--add"
        :aria-label="$t('shopping.newList')"
        :title="$t('shopping.newList')"
        @click="showNewListDialog = true"
      >
        <PhPlus :size="16" weight="bold" />
      </button>
    </div>

    <!-- Erstes Laden: Platzhalter statt aufblitzendem Leerzustand -->
    <div v-if="!loadedOnce && shoppingStore.lists.length === 0" class="skeleton-list">
      <BaseSkeleton v-for="n in 3" :key="n" :width="['75%', '60%', '85%'][n - 1]" height="16px" />
    </div>

    <!-- Fehlerzustand: Listen konnten nicht geladen werden -->
    <BaseErrorState
      v-else-if="loadError && shoppingStore.lists.length === 0"
      :retrying="reloading"
      @retry="reload"
    />

    <!-- Empty-State wenn keine Listen vorhanden -->
    <BaseEmptyState
      v-else-if="shoppingStore.lists.length === 0"
      :icon="PhShoppingCart"
      :title="$t('shopping.noListsTitle')"
      :subtitle="$t('shopping.noListsSubtitle')"
    >
      <template #action>
        <button type="button" class="btn-primary" @click="showNewListDialog = true">
          {{ $t('shopping.createFirstList') }}
        </button>
      </template>
    </BaseEmptyState>

    <!-- Inhalt der aktiven Liste -->
    <ShoppingList
      v-if="shoppingStore.activeListId"
      :auto-focus="autoFocus"
      :load-error="loadError"
      :retrying="reloading"
      @retry="reload"
    />

    <!-- Neue-Liste-Dialog -->
    <BaseDialog
      :open="showNewListDialog"
      :title="$t('shopping.newList')"
      @close="showNewListDialog = false"
    >
      <form @submit.prevent="handleCreateList">
        <input
          v-model="newListName"
          type="text"
          :placeholder="$t('shopping.newListPlaceholder')"
          class="dialog-input"
          autofocus
        />
        <div class="dialog-actions">
          <button type="button" class="btn-secondary" @click="showNewListDialog = false">
            {{ $t('common.cancel') }}
          </button>
          <button type="submit" class="btn-primary" :disabled="!newListName.trim() || isPending('createList')">
            {{ $t('common.add') }}
          </button>
        </div>
      </form>
    </BaseDialog>

    <!-- Liste-bearbeiten-Dialog -->
    <BaseDialog
      :open="showEditListDialog"
      :title="$t('shopping.editList')"
      @close="showEditListDialog = false"
    >
      <form @submit.prevent="handleRenameList">
        <input
          v-model="editListName"
          type="text"
          :placeholder="$t('shopping.newListPlaceholder')"
          :aria-label="$t('shopping.listName')"
          class="dialog-input"
          maxlength="100"
        />
        <p v-if="confirmingListDelete" class="dialog-warning" role="alert">
          {{ activeListItemCount > 0
            ? $t('shopping.deleteListNotEmpty', { count: activeListItemCount })
            : $t('shopping.deleteListConfirm', { name: activeList?.name ?? '' }) }}
        </p>
        <div class="dialog-actions dialog-actions--split">
          <button
            type="button"
            class="btn-danger-text"
            :disabled="isPending('editList')"
            @click="handleDeleteList"
          >
            {{ $t('shopping.deleteList') }}
          </button>
          <div class="dialog-actions">
            <button type="button" class="btn-secondary" @click="showEditListDialog = false">
              {{ $t('common.cancel') }}
            </button>
            <button
              v-if="!confirmingListDelete"
              type="submit"
              class="btn-primary"
              :disabled="!editListName.trim() || isPending('editList')"
            >
              {{ $t('common.save') }}
            </button>
          </div>
        </div>
      </form>
    </BaseDialog>
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.list-pills {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: var(--space-1);
}

.pill-tab {
  padding: 6px 16px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: all 150ms;
  border: none;
  font-family: var(--font-family);
  background: var(--chip);
  color: var(--ink);
}

.pill-tab--active {
  background: var(--ink);
  color: var(--card);
}

.pill-tab--add {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  background: var(--chip);
  color: var(--ink-secondary);
}

.pill-tab--add:active {
  background: var(--ink);
  color: var(--card);
}

.dialog-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  margin-bottom: var(--space-4);
}

.dialog-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
}

.dialog-actions--split {
  justify-content: space-between;
  align-items: center;
}

.dialog-warning {
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-danger);
}

.btn-danger-text {
  padding: 8px 0;
  border: none;
  background: transparent;
  color: var(--color-danger);
  font-weight: 600;
  font-size: var(--text-sm);
  font-family: var(--font-family);
  cursor: pointer;
}

.btn-danger-text:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.btn-primary {
  padding: 8px 20px;
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: var(--text-sm);
  border: none;
  cursor: pointer;
  font-family: var(--font-family);
  background: var(--ink);
  color: var(--card);
}

.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 8px 20px;
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: var(--text-sm);
  border: none;
  cursor: pointer;
  font-family: var(--font-family);
  background: transparent;
  color: var(--ink-secondary);
}
</style>
