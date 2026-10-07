<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useShoppingStore } from '../stores/shopping'
import { useI18n } from 'vue-i18n'
import { useToast } from '../composables/useToast'
import ShoppingList from '../components/ShoppingList.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import { PhPlus, PhShoppingCart } from '@phosphor-icons/vue'

const route = useRoute()
const router = useRouter()
const shoppingStore = useShoppingStore()
const { t } = useI18n()
const { showToast } = useToast()

const autoFocus = computed(() => route.query.new === '1')

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
  try {
    await shoppingStore.createList(name)
    newListName.value = ''
    showNewListDialog.value = false
  } catch {
    showToast(t('shopping.createListError'), 'error')
  }
}

// Gesamtzahl offener Items über alle Listen — lokal berechnet
const totalOpenCount = computed(() =>
  shoppingStore.items.filter(i => !i.is_checked).length,
)

onMounted(async () => {
  await shoppingStore.fetchLists()
  shoppingStore.fetchItems()
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
      <button
        v-for="tab in listTabs"
        :key="tab.key"
        type="button"
        class="pill-tab tap-target"
        :class="{ 'pill-tab--active': activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
      <button
        type="button"
        class="pill-tab pill-tab--add tap-target"
        @click="showNewListDialog = true"
      >
        <PhPlus :size="16" weight="bold" />
      </button>
    </div>

    <!-- Empty-State wenn keine Listen vorhanden -->
    <BaseEmptyState
      v-if="!shoppingStore.loading && shoppingStore.lists.length === 0"
      :icon="PhShoppingCart"
      :title="$t('shopping.noListsTitle')"
      :subtitle="$t('shopping.noListsSubtitle')"
    >
      <template #action>
        <button type="button" class="btn-primary tap-target" @click="showNewListDialog = true">
          {{ $t('shopping.createFirstList') }}
        </button>
      </template>
    </BaseEmptyState>

    <!-- Inhalt der aktiven Liste -->
    <ShoppingList
      v-if="shoppingStore.activeListId"
      :auto-focus="autoFocus"
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
          <button type="button" class="btn-secondary tap-target" @click="showNewListDialog = false">
            {{ $t('common.cancel') }}
          </button>
          <button type="submit" class="btn-primary tap-target" :disabled="!newListName.trim()">
            {{ $t('common.add') }}
          </button>
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
  /* Raum für die vergrösserte Tap-Fläche (Scroll-Container schneidet sonst ab) */
  padding-block: var(--space-2) var(--space-3);
  margin-block: calc(-1 * var(--space-2)) calc(-1 * var(--space-2));
  padding-inline-end: var(--space-1);
}

/* Gleiche Tokens wie components/ui/BasePillTabs.vue */
.pill-tab {
  padding: var(--chip-padding);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
  border: none;
  font-family: var(--font-family);
  background: var(--chip);
  color: var(--ink);
}

.pill-tab:active {
  transform: scale(0.97);
}

.pill-tab--active {
  background: var(--ink);
  color: var(--card);
}

.pill-tab--add {
  /* bleibt bei langen Listennamen rechts sichtbar statt aus dem Bild zu scrollen */
  position: sticky;
  right: 0;
  flex-shrink: 0;
  box-shadow: 0 0 0 var(--space-2) var(--bg);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-1-5) var(--space-3);
  background: var(--chip);
  color: var(--sub);
}

.pill-tab--add:active {
  background: var(--ink);
  color: var(--card);
}

.dialog-input {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
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

.btn-primary {
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-semibold);
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
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-sm);
  border: none;
  cursor: pointer;
  font-family: var(--font-family);
  background: transparent;
  color: var(--sub);
}
</style>
