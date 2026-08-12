<script setup lang="ts">
import { ref, computed, onMounted, nextTick, onUnmounted } from 'vue'
import { useShoppingStore } from '../stores/shopping'
import { useExpensesStore } from '../stores/expenses'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { PhX, PhShoppingCart, PhCaretDown, PhPlus, PhDotsThreeVertical } from '@phosphor-icons/vue'
import type { ShoppingItem } from '../types'
import BaseSkeleton from './ui/BaseSkeleton.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'
import BaseCheckCircle from './ui/BaseCheckCircle.vue'
import BaseDialog from './ui/BaseDialog.vue'
import ShoppingItemEditSheet from './ShoppingItemEditSheet.vue'

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

// ── Edit-Sheet State ──
const editItem = ref<ShoppingItem | null>(null)
const showEditSheet = ref(false)

// ── Rename / Dissolve Dialog State ──
const showRenameDialog = ref(false)
const showDissolveDialog = ref(false)
const renameTarget = ref<string>('')
const renameNewName = ref('')
const dissolveTarget = ref<string>('')
const kebabOpen = ref<string | null>(null)

// Kebab schliessen bei Klick ausserhalb
function handleDocumentClick() {
  if (kebabOpen.value) {
    kebabOpen.value = null
  }
}
onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  if (props.autoFocus) {
    nextTick(() => inputRef.value?.focus())
  }
})
onUnmounted(() => {
  document.removeEventListener('click', handleDocumentClick)
})

function resolveUserName(userId: string | null): string | null {
  if (!userId) return null
  const member = expensesStore.members.find(m => m.id === userId)
  return member?.display_name ?? null
}

// ── Items gefiltert nach aktiver Liste + Store-Filter ──
const openItems = computed(() => {
  const filter = shoppingStore.activeStoreFilter
  return shoppingStore.activeListItems.filter(item => {
    if (item.is_checked) return false
    if (filter === null) return true // "Alle"
    if (filter === '__none__') return !item.store
    return item.store === filter
  })
})

const checkedItems = computed(() => {
  const filter = shoppingStore.activeStoreFilter
  return shoppingStore.activeListItems.filter(item => {
    if (!item.is_checked) return false
    if (filter === null) return true
    if (filter === '__none__') return !item.store
    return item.store === filter
  })
})

// ── Gruppierte offene Items ──
const groupedItems = computed(() => {
  const items = openItems.value
  if (shoppingStore.activeStoreFilter !== null) {
    // Einzelnes Geschäft → keine Gruppen
    return new Map([['', items]])
  }

  // "Alle" → nach Geschäft gruppieren
  const groups = new Map<string, ShoppingItem[]>()
  const misc = t('shopping.miscGroup')

  for (const item of items) {
    const key = item.store || misc
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(item)
  }

  // "Sonstiges" ans Ende
  if (groups.has(misc)) {
    const miscItems = groups.get(misc)!
    groups.delete(misc)
    groups.set(misc, miscItems)
  }

  return groups
})

// Prüfe ob Gruppierung sinnvoll ist (mindestens 2 verschiedene Gruppen)
const hasMultipleGroups = computed(() => groupedItems.value.size > 1)

// ── Store-Chips ──
const storeChips = computed(() => {
  const allItems = shoppingStore.activeListItems.filter(i => !i.is_checked)
  const chips: Array<{ key: string | null; label: string; count: number }> = [
    { key: null, label: t('shopping.allStores'), count: allItems.length },
  ]

  for (const store of shoppingStore.stores) {
    const count = allItems.filter(i => i.store === store).length
    if (count > 0) {
      chips.push({ key: store, label: store, count })
    }
  }

  // "Sonstiges" zeigen wenn Items ohne Store existieren
  const noStoreCount = allItems.filter(i => !i.store).length
  if (noStoreCount > 0 && shoppingStore.stores.length > 0) {
    chips.push({ key: '__none__', label: t('shopping.miscGroup'), count: noStoreCount })
  }

  return chips
})

// ── Verfügbare Kategorien für datalist ──
const availableCategories = computed(() => {
  const cats = new Set<string>()
  for (const item of shoppingStore.activeListItems) {
    if (item.category) cats.add(item.category)
  }
  return [...cats].sort()
})

// ── Actions ──
async function handleAddItem() {
  const name = newItemName.value.trim()
  if (!name) return

  newItemName.value = ''
  try {
    // Store automatisch von aktivem Filter übernehmen
    const storeForItem = shoppingStore.activeStoreFilter === '__none__'
      ? undefined
      : (shoppingStore.activeStoreFilter ?? undefined)
    await shoppingStore.addItem(name, undefined, undefined, storeForItem)
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

// ── Edit-Sheet ──
function handleItemTap(item: ShoppingItem) {
  editItem.value = { ...item }
  showEditSheet.value = true
}

async function handleEditSave(data: { name: string; quantity: string | null; store: string | null; category: string | null }) {
  if (!editItem.value) return
  try {
    await shoppingStore.updateItem(editItem.value.id, data)
    showEditSheet.value = false
    editItem.value = null
  } catch {
    showToast(t('shopping.toggleError'), 'error')
  }
}

// ── Kebab-Menü Actions ──
function handleRenameStore(storeName: string) {
  renameTarget.value = storeName
  renameNewName.value = storeName
  showRenameDialog.value = true
  kebabOpen.value = null
}

async function confirmRename() {
  const newName = renameNewName.value.trim()
  if (!newName || newName === renameTarget.value) {
    showRenameDialog.value = false
    return
  }

  // Merge-Warnung: Prüfe ob Ziel-Store bereits existiert
  if (shoppingStore.stores.includes(newName)) {
    const existingCount = shoppingStore.activeListItems.filter(i => i.store === newName).length
    const confirmed = window.confirm(
      t('shopping.mergeStoreConfirm', { to: newName, count: existingCount })
    )
    if (!confirmed) return
  }

  try {
    await shoppingStore.reassignStore(renameTarget.value, newName)
    showToast(t('shopping.storeRenamed'), 'success')
  } catch {
    showToast(t('shopping.reassignError'), 'error')
  }
  showRenameDialog.value = false
}

function handleDissolveStore(storeName: string) {
  dissolveTarget.value = storeName
  showDissolveDialog.value = true
  kebabOpen.value = null
}

async function confirmDissolve() {
  try {
    await shoppingStore.reassignStore(dissolveTarget.value, null)
    showToast(t('shopping.storeDissolved'), 'success')
  } catch {
    showToast(t('shopping.reassignError'), 'error')
  }
  showDissolveDialog.value = false
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
      <button
        type="submit"
        class="quick-add__btn"
        :disabled="!newItemName.trim()"
        :aria-label="$t('common.add')"
      >
        <PhPlus :size="20" weight="bold" />
      </button>
    </form>

    <!-- Store-Chips -->
    <div v-if="storeChips.length > 1" class="store-chips">
      <button
        v-for="chip in storeChips"
        :key="chip.key ?? 'all'"
        type="button"
        class="store-chip"
        :class="{ 'store-chip--active': shoppingStore.activeStoreFilter === chip.key }"
        @click="shoppingStore.setStoreFilter(chip.key)"
      >
        {{ chip.label }}
        <span class="store-chip__badge">{{ chip.count }}</span>
      </button>
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
        <h3 v-if="hasMultipleGroups && groupName" class="group-header">
          <span>{{ groupName }}</span>
          <span class="group-header__count">{{ groupItems.length }}</span>
          <button
            v-if="groupName !== $t('shopping.miscGroup')"
            type="button"
            class="group-header__kebab"
            @click.stop="kebabOpen = kebabOpen === groupName ? null : groupName"
          >
            <PhDotsThreeVertical :size="18" />
          </button>
          <!-- Kebab-Dropdown -->
          <div v-if="kebabOpen === groupName" class="kebab-menu" @click.stop>
            <button @click="handleRenameStore(groupName)">{{ $t('shopping.renameStore') }}</button>
            <button @click="handleDissolveStore(groupName)">{{ $t('shopping.dissolveStore') }}</button>
          </div>
        </h3>
        <ul class="item-list">
          <li
            v-for="item in groupItems"
            :key="item.id"
            class="item-row"
          >
            <BaseCheckCircle :checked="item.is_checked" @toggle="handleToggle(item.id)" />
            <span class="item-row__name" @click.stop="handleItemTap(item)">{{ item.name }}</span>
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

    <!-- Edit-Sheet -->
    <ShoppingItemEditSheet
      :item="editItem"
      :stores="shoppingStore.stores"
      :categories="availableCategories"
      :open="showEditSheet"
      @close="showEditSheet = false; editItem = null"
      @save="handleEditSave"
    />

    <!-- Rename-Dialog -->
    <BaseDialog
      :open="showRenameDialog"
      :title="$t('shopping.renameStore')"
      @close="showRenameDialog = false"
    >
      <form @submit.prevent="confirmRename">
        <input v-model="renameNewName" type="text" class="dialog-input"
               :placeholder="$t('shopping.renameStorePlaceholder')" maxlength="100" autofocus />
        <div class="dialog-actions">
          <button type="button" class="btn-secondary" @click="showRenameDialog = false">{{ $t('common.cancel') }}</button>
          <button type="submit" class="btn-primary" :disabled="!renameNewName.trim()">{{ $t('common.save') }}</button>
        </div>
      </form>
    </BaseDialog>

    <!-- Dissolve-Dialog -->
    <BaseDialog
      :open="showDissolveDialog"
      :title="$t('shopping.dissolveStore')"
      danger
      @close="showDissolveDialog = false"
    >
      <p>{{ $t('shopping.dissolveConfirm', { store: dissolveTarget }) }}</p>
      <template #footer>
        <button type="button" class="btn-secondary" @click="showDissolveDialog = false">{{ $t('common.cancel') }}</button>
        <button type="button" class="btn-danger" @click="confirmDissolve">{{ $t('shopping.dissolveStore') }}</button>
      </template>
    </BaseDialog>
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
  display: flex;
  gap: var(--space-2);
  align-items: center;
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
  flex: 1;
  min-width: 0;
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

.quick-add__btn {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  border: none;
  background: var(--acc);
  color: var(--card);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}
.quick-add__btn:active {
  transform: scale(0.92);
}
.quick-add__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Store-Chips */
.store-chips {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: var(--space-1);
}

.store-chip {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 6px 14px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  cursor: pointer;
  border: none;
  font-family: var(--font-family);
  background: var(--chip);
  color: var(--ink);
  transition: all 150ms;
  min-height: 44px;
}

.store-chip--active {
  background: var(--ink);
  color: var(--card);
}

.store-chip__badge {
  font-size: var(--text-xs);
  background: rgba(0,0,0,0.1);
  border-radius: var(--radius-full);
  padding: 1px 6px;
  min-width: 20px;
  text-align: center;
}

.store-chip--active .store-chip__badge {
  background: rgba(255,255,255,0.2);
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
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 var(--space-1) var(--space-2);
  position: relative;
}

.group-header__count {
  font-size: var(--text-xs);
  color: var(--sub);
}

.group-header__kebab {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  min-width: 44px;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  margin-left: auto;
}

.kebab-menu {
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 20;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-btn);
  box-shadow: var(--shadow-overlay);
  min-width: 180px;
  overflow: hidden;
}

.kebab-menu button {
  display: block;
  width: 100%;
  text-align: left;
  padding: var(--space-3) var(--space-4);
  border: none;
  background: none;
  font-size: var(--text-sm);
  font-family: var(--font-family);
  color: var(--ink);
  cursor: pointer;
}

.kebab-menu button:hover {
  background: var(--chip);
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
  transition: background var(--transition-fast);
  -webkit-user-select: none;
  user-select: none;
}

.item-row__name {
  flex: 1;
  font-size: var(--text-base);
  color: var(--ink);
  cursor: pointer;
}

.item-row__name:active {
  opacity: 0.7;
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

/* Dialog-Styles */
.dialog-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  margin-bottom: var(--space-3);
}

.dialog-input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.btn-primary {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-btn);
  border: none;
  background: var(--acc);
  color: var(--card);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-family);
  cursor: pointer;
  min-height: 44px;
  transition: opacity var(--transition-fast);
}

.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-secondary {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-btn);
  border: 1px solid var(--line-strong);
  background: var(--card);
  color: var(--ink);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-family);
  cursor: pointer;
  min-height: 44px;
  transition: background var(--transition-fast);
}

.btn-secondary:hover {
  background: var(--chip);
}

.btn-danger {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-btn);
  border: none;
  background: var(--color-danger);
  color: var(--card);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-family);
  cursor: pointer;
  min-height: 44px;
  transition: opacity var(--transition-fast);
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
