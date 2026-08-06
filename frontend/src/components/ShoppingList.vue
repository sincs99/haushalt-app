<script setup lang="ts">
import { ref, computed } from 'vue'
import { useShoppingStore } from '../stores/shopping'
import { useExpensesStore } from '../stores/expenses'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { X, ShoppingCart, ChevronDown } from 'lucide-vue-next'
import BaseSkeleton from './ui/BaseSkeleton.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'

const shoppingStore = useShoppingStore()
const expensesStore = useExpensesStore()
const { showToast } = useToast()
const { t } = useI18n()

const newItemName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const showDone = ref(false)

function resolveUserName(userId: string | null): string | null {
  if (!userId) return null
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? null
}

// Getrennte Listen: offen vs. abgehakt
const openItems = computed(() =>
  shoppingStore.items.filter((item) => !item.is_checked)
)
const checkedItems = computed(() =>
  shoppingStore.items.filter((item) => item.is_checked)
)

async function handleAddItem() {
  const name = newItemName.value.trim()
  if (!name) return

  newItemName.value = ''
  try {
    await shoppingStore.addItem(name)
  } catch {
    showToast(t('shopping.addError'))
  }
  // Fokus bleibt im Feld — UX-Prinzip "Quick-Add in unter 3 Sekunden"
  inputRef.value?.focus()
}

async function handleToggle(itemId: string) {
  try {
    await shoppingStore.toggleChecked(itemId)
  } catch {
    showToast(t('shopping.toggleError'))
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
        ).catch(() => {
          showToast(t('shopping.addError'), 'error')
        })
      },
    })
  } catch {
    showToast(t('shopping.deleteError'))
  }
}

async function handleClearDone() {
  const itemsToDelete = [...checkedItems.value]
  if (itemsToDelete.length === 0) return

  // Lösche alle abgehakten Items
  await Promise.all(
    itemsToDelete.map(item => shoppingStore.deleteItem(item.id).catch(() => {}))
  )

  // Undo-Toast: alle gelöschten Items wieder anlegen
  showToast(t('common.listCleared'), 'success', undefined, {
    label: t('common.undo'),
    onAction: () => {
      Promise.all(
        itemsToDelete.map(item =>
          shoppingStore.addItem(
            item.name,
            item.quantity ?? undefined,
            item.category ?? undefined,
          ).catch(() => {})
        )
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

    <!-- Skeleton Loading -->
    <div v-if="shoppingStore.loading && shoppingStore.items.length === 0" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="20px" height="20px" rounded />
        <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
      </div>
    </div>

    <!-- Offene Items -->
    <ul v-if="openItems.length > 0" class="item-list">
      <li
        v-for="item in openItems"
        :key="item.id"
        class="item-row"
        @click="handleToggle(item.id)"
      >
        <span class="item-row__check">
          <input
            type="checkbox"
            :checked="item.is_checked"
            @click.stop
            @change="handleToggle(item.id)"
            class="item-row__checkbox"
          />
        </span>
        <span class="item-row__name">{{ item.name }}</span>
        <span v-if="item.quantity" class="item-row__meta">{{ item.quantity }}</span>
        <BaseAvatar
          v-if="item.added_by_user_id && resolveUserName(item.added_by_user_id)"
          :name="resolveUserName(item.added_by_user_id)!"
          :user-id="item.added_by_user_id"
          size="sm"
        />
      </li>
    </ul>

    <!-- Empty State -->
    <BaseEmptyState
      v-if="!shoppingStore.loading && openItems.length === 0"
      :icon="ShoppingCart"
      :title="$t('shopping.emptyOpenTitle')"
      :subtitle="$t('shopping.emptyOpenSubtitle')"
    />

    <!-- Erledigt-Sektion (einklappbar) -->
    <div v-if="checkedItems.length > 0" class="done-section">
      <div class="done-section__header">
        <button type="button" class="done-section__toggle" @click="showDone = !showDone">
          <ChevronDown
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
            <span class="item-row__check" @click="handleToggle(item.id)">
              <input
                type="checkbox"
                :checked="item.is_checked"
                @click.stop
                @change="handleToggle(item.id)"
                class="item-row__checkbox"
              />
            </span>
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
              <X :size="16" />
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
  background: var(--color-bg);
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
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-base); /* 16px — iOS-Zoom-Prevention */
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
  transition: border-color var(--transition-fast);
}

.quick-add__input::placeholder {
  color: var(--color-text-muted);
}

.quick-add__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
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
  border-bottom: 1px solid var(--color-neutral-200);
  cursor: pointer;
  transition: background var(--transition-fast);
  -webkit-user-select: none;
  user-select: none;
}

.item-row:active {
  background: var(--color-neutral-50);
}

@media (hover: hover) {
  .item-row:hover {
    background: var(--color-neutral-50);
  }
}

.item-row__check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.item-row__checkbox {
  width: 20px;
  height: 20px;
  accent-color: var(--color-primary);
  cursor: pointer;
}

.item-row__name {
  flex: 1;
  font-size: var(--text-base);
  color: var(--color-text);
}

.item-row__meta {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

/* Abgehakte Items: gedämpft */
.item-row--checked {
  opacity: 0.55;
}

.item-row--checked .item-row__name {
  text-decoration: line-through;
  color: var(--color-text-muted);
}

/* Löschen-Button */
.item-row__delete {
  background: none;
  border: none;
  color: var(--color-text-muted);
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
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  padding: var(--space-1) 0;
}

.done-section__toggle:hover {
  color: var(--color-text-secondary);
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
  color: var(--color-text-muted);
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
