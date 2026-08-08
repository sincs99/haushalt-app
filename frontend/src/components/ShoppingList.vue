<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useShoppingStore } from '../stores/shopping'
import { useExpensesStore } from '../stores/expenses'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { PhX, PhShoppingCart, PhCaretDown } from '@phosphor-icons/vue'
import type { ShoppingItem } from '../types'
import BaseSkeleton from './ui/BaseSkeleton.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'
import BaseCheckCircle from './ui/BaseCheckCircle.vue'
import BasePillTabs from './ui/BasePillTabs.vue'

const shoppingStore = useShoppingStore()
const expensesStore = useExpensesStore()
const { showToast } = useToast()
const { t } = useI18n()

const props = withDefaults(defineProps<{
  autoFocus?: boolean
}>(), {
  autoFocus: false,
})

const newItemName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const showDone = ref(false)

// ── Gruppierung ──
type GroupBy = 'store' | 'category'
const groupBy = ref<GroupBy>('category')

const groupTabs = computed(() => [
  { key: 'category', label: t('shopping.groupByCategory') },
  { key: 'store', label: t('shopping.groupByStore') },
])

onMounted(() => {
  if (props.autoFocus) {
    nextTick(() => inputRef.value?.focus())
  }
})

function resolveUserName(userId: string | null): string | null {
  if (!userId) return null
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? null
}

// ── Items gefiltert nach aktiver Liste ──
const openItems = computed(() =>
  shoppingStore.activeListItems.filter(item => !item.is_checked),
)

const checkedItems = computed(() =>
  shoppingStore.activeListItems.filter(item => item.is_checked),
)

// ── Gruppierte offene Items ──
const groupedItems = computed(() => {
  const items = openItems.value
  const groups = new Map<string, ShoppingItem[]>()

  for (const item of items) {
    const key = groupBy.value === 'store'
      ? (item.store || t('shopping.miscGroup'))
      : (item.category || t('shopping.miscGroup'))

    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(item)
  }

  return groups
})

// Prüfe ob Gruppierung sinnvoll ist (mindestens 2 verschiedene Gruppen)
const hasMultipleGroups = computed(() => groupedItems.value.size > 1)

// ── Actions ──
async function handleAddItem() {
  const name = newItemName.value.trim()
  if (!name) return

  newItemName.value = ''
  try {
    await shoppingStore.addItem(name)
  } catch {
    showToast(t('shopping.addError'), 'error')
  }
  inputRef.value?.focus()
}

async function handleToggle(itemId: string) {
  try {
    await shoppingStore.toggleChecked(itemId)
  } catch {
    showToast(t('shopping.toggleError'), 'error')
  }
}

async function handleAssignToggle(itemId: string) {
  try {
    await shoppingStore.toggleAssigned(itemId)
  } catch {
    showToast(t('shopping.toggleError'), 'error')
  }
}

async function handleDelete(itemId: string) {
  const item = shoppingStore.items.find(i => i.id === itemId)
  if (!item) return

  try {
    await shoppingStore.deleteItem(itemId)
    showToast(t('common.deleted'), 'success', undefined, {
      label: t('common.undo'),
      onAction: () => {
        shoppingStore.addItem(
          item.name,
          item.quantity ?? undefined,
          item.category ?? undefined,
          item.store ?? undefined,
        ).catch(() => {
          showToast(t('shopping.addError'), 'error')
        })
      },
    })
  } catch {
    showToast(t('shopping.deleteError'), 'error')
  }
}

async function handleClearDone() {
  const itemsToDelete = [...checkedItems.value]
  if (itemsToDelete.length === 0) return

  await Promise.all(
    itemsToDelete.map(item => shoppingStore.deleteItem(item.id).catch(() => {})),
  )

  showToast(t('common.listCleared'), 'success', undefined, {
    label: t('common.undo'),
    onAction: () => {
      Promise.all(
        itemsToDelete.map(item =>
          shoppingStore.addItem(
            item.name,
            item.quantity ?? undefined,
            item.category ?? undefined,
            item.store ?? undefined,
          ).catch(() => {}),
        ),
      )
    },
  })
}
</script>

<template>
  <div class="shopping-list">
    <!-- Quick-Add-Input (sticky auf Mobile) -->
    <form @submit.prevent="handleAddItem" class="quick-add">
      <input
        ref="inputRef"
        v-model="newItemName"
        type="text"
        :placeholder="$t('shopping.addPlaceholder')"
        class="quick-add__input"
        autofocus
      />
    </form>

    <!-- Gruppierungs-Umschalter -->
    <div v-if="openItems.length > 0" class="group-toggle">
      <BasePillTabs
        :tabs="groupTabs"
        :model-value="groupBy"
        @update:model-value="groupBy = ($event as GroupBy)"
      />
    </div>

    <!-- Skeleton Loading -->
    <div v-if="shoppingStore.loading && shoppingStore.items.length === 0" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="20px" height="20px" rounded />
        <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
      </div>
    </div>

    <!-- Gruppierte offene Items -->
    <div v-if="openItems.length > 0" class="item-groups">
      <div
        v-for="[groupName, groupItems] in groupedItems"
        :key="groupName"
        class="group"
      >
        <h3 v-if="hasMultipleGroups" class="group-header">{{ groupName }}</h3>
        <ul class="item-list">
          <li
            v-for="item in groupItems"
            :key="item.id"
            class="item-row"
            @click="handleToggle(item.id)"
          >
            <BaseCheckCircle :checked="item.is_checked" @toggle="handleToggle(item.id)" />
            <span class="item-row__name">{{ item.name }}</span>
            <span v-if="item.quantity" class="item-row__meta">{{ item.quantity }}</span>
            <button
              type="button"
              class="item-row__assign"
              :title="item.assigned_to_user_id ? $t('shopping.unassign') : $t('shopping.assignToMe')"
              @click.stop="handleAssignToggle(item.id)"
            >
              <BaseAvatar
                v-if="item.assigned_to_user_id && resolveUserName(item.assigned_to_user_id)"
                :name="resolveUserName(item.assigned_to_user_id)!"
                :user-id="item.assigned_to_user_id"
                size="sm"
              />
              <span v-else class="assign-circle" />
            </button>
          </li>
        </ul>
      </div>
    </div>

    <!-- Empty State -->
    <BaseEmptyState
      v-if="!shoppingStore.loading && openItems.length === 0"
      :icon="PhShoppingCart"
      :title="$t('shopping.emptyOpenTitle')"
      :subtitle="$t('shopping.emptyOpenSubtitle')"
    />

    <!-- Erledigt-Sektion (einklappbar) -->
    <div v-if="checkedItems.length > 0" class="done-section">
      <div class="done-section__header">
        <button type="button" class="done-section__toggle" @click="showDone = !showDone">
          <PhCaretDown
            :size="18"
            class="done-section__chevron"
            :class="{ 'done-section__chevron--open': showDone }"
          />
          {{ $t('shopping.doneCount', { count: checkedItems.length }) }}
        </button>
        <button
          v-if="showDone"
          type="button"
          class="done-section__clear-btn"
          @click="handleClearDone"
        >
          {{ $t('shopping.clearDone') }}
        </button>
      </div>

      <Transition name="collapse">
        <ul v-if="showDone" class="item-list">
          <li
            v-for="item in checkedItems"
            :key="item.id"
            class="item-row item-row--checked"
          >
            <BaseCheckCircle :checked="item.is_checked" @toggle="handleToggle(item.id)" />
            <span class="item-row__name" @click="handleToggle(item.id)">{{ item.name }}</span>
            <span v-if="item.quantity" class="item-row__meta">{{ item.quantity }}</span>
            <BaseAvatar
              v-if="item.added_by_user_id && resolveUserName(item.added_by_user_id)"
              :name="resolveUserName(item.added_by_user_id)!"
              :user-id="item.added_by_user_id"
              size="sm"
            />
            <button
              class="item-row__delete"
              @click.stop="handleDelete(item.id)"
              :title="$t('common.delete')"
              :aria-label="$t('common.delete')"
            >
              <PhX :size="16" />
            </button>
          </li>
        </ul>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.shopping-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Quick-Add: sticky auf Mobile */
.quick-add {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg);
  padding-bottom: var(--space-2);
}

@media (min-width: 768px) {
  .quick-add {
    position: static;
  }
}

.quick-add__input {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-size: var(--text-base); /* 16px — iOS-Zoom-Prevention */
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  transition: border-color var(--transition-fast);
}

.quick-add__input::placeholder {
  color: var(--sub);
}

.quick-add__input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

/* Gruppierungs-Umschalter */
.group-toggle {
  display: flex;
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

/* Gruppen */
.item-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.group-header {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 var(--space-1) var(--space-2);
}

/* Item-Liste */
.item-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}

/* Item-Zeile: grosszügiges Touch-Target */
.item-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-2);
  min-height: 48px; /* Touch-Target */
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  transition: background var(--transition-fast);
  -webkit-user-select: none;
  user-select: none;
}

.item-row:active {
  background: var(--chip);
}

@media (hover: hover) {
  .item-row:hover {
    background: var(--chip);
  }
}

.item-row__name {
  flex: 1;
  font-size: var(--text-base);
  color: var(--ink);
}

.item-row__meta {
  font-size: var(--text-sm);
  color: var(--sub);
  flex-shrink: 0;
}

/* Zuweisungs-Button */
.item-row__assign {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.assign-circle {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-full);
  border: 2px dashed var(--line-strong);
  display: block;
  flex-shrink: 0;
}

/* Abgehakte Items: durchgestrichen + sub-Farbe (NICHT opacity) */
.item-row--checked .item-row__name {
  text-decoration: line-through;
  color: var(--sub);
}

/* Löschen-Button */
.item-row__delete {
  background: none;
  border: none;
  color: var(--sub);
  cursor: pointer;
  font-size: var(--text-base);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
  flex-shrink: 0;
  min-width: 44px;
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.item-row__delete:hover {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

/* Erledigt-Sektion */
.done-section {
  margin-top: var(--space-2);
}

.done-section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) 0;
}

.done-section__toggle {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  background: none;
  border: none;
  color: var(--sub);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  padding: var(--space-1) 0;
}

.done-section__toggle:hover {
  color: var(--ink);
}

.done-section__chevron {
  transition: transform var(--transition-normal);
  transform: rotate(-90deg);
}

.done-section__chevron--open {
  transform: rotate(0deg);
}

.done-section__clear-btn {
  background: none;
  border: none;
  color: var(--sub);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  transition: color var(--transition-fast), background var(--transition-fast);
}

.done-section__clear-btn:hover {
  color: var(--color-danger);
  background: var(--color-danger-light);
}

/* Collapse-Transition */
.collapse-enter-active,
.collapse-leave-active {
  transition: all var(--transition-normal);
  overflow: hidden;
}

.collapse-enter-from,
.collapse-leave-to {
  opacity: 0;
  max-height: 0;
}

.collapse-enter-to,
.collapse-leave-from {
  opacity: 1;
  max-height: 1000px;
}
</style>
