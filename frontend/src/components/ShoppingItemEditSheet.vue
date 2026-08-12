<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ShoppingItem } from '../types'
import BaseDialog from './ui/BaseDialog.vue'

const props = defineProps<{
  item: ShoppingItem | null
  stores: string[]
  categories: string[]
  open: boolean
}>()

const emit = defineEmits<{
  close: []
  save: [data: { name: string; quantity: string | null; store: string | null; category: string | null }]
}>()

const { t } = useI18n()

const name = ref('')
const quantity = ref('')
const store = ref<string | null>(null)
const category = ref('')
const newStoreName = ref('')

// Sync form wenn Item sich ändert
watch(() => props.item, (item) => {
  if (item) {
    name.value = item.name
    quantity.value = item.quantity ?? ''
    store.value = item.store
    category.value = item.category ?? ''
    newStoreName.value = ''
  }
}, { immediate: true })

const canSave = computed(() => name.value.trim().length > 0)

function selectStore(s: string) {
  if (store.value === s) {
    store.value = null
  } else {
    store.value = s
  }
  newStoreName.value = ''
}

function handleNewStoreInput() {
  const trimmed = newStoreName.value.trim()
  if (trimmed) {
    store.value = trimmed
  } else {
    // Wenn Freitext gelöscht wird und kein Chip aktiv, Store null
    if (!props.stores.includes(store.value ?? '')) {
      store.value = null
    }
  }
}

function handleSubmit() {
  if (!canSave.value) return
  emit('save', {
    name: name.value.trim(),
    quantity: quantity.value.trim() || null,
    store: store.value,
    category: category.value.trim() || null,
  })
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('shopping.editItem')"
    @close="emit('close')"
  >
    <form @submit.prevent="handleSubmit" class="edit-form">
      <!-- Name -->
      <label class="edit-field">
        <span class="edit-field__label">{{ t('shopping.itemName') }}</span>
        <input
          v-model="name"
          type="text"
          class="edit-field__input"
          maxlength="200"
          required
          autofocus
        />
      </label>

      <!-- Menge -->
      <label class="edit-field">
        <span class="edit-field__label">{{ t('shopping.itemQuantity') }}</span>
        <input
          v-model="quantity"
          type="text"
          class="edit-field__input"
          maxlength="50"
          :placeholder="t('shopping.quantityPlaceholder')"
        />
      </label>

      <!-- Geschäft -->
      <div class="edit-field">
        <span class="edit-field__label">{{ t('shopping.itemStore') }}</span>
        <div class="store-picker">
          <button
            v-for="s in stores"
            :key="s"
            type="button"
            class="store-pick-chip"
            :class="{ 'store-pick-chip--active': store === s }"
            @click="selectStore(s)"
          >
            {{ s }}
          </button>
          <input
            v-model="newStoreName"
            type="text"
            class="store-pick-input"
            :placeholder="t('shopping.newStore')"
            maxlength="100"
            @input="handleNewStoreInput"
            @blur="handleNewStoreInput"
          />
        </div>
      </div>

      <!-- Abteilung -->
      <label class="edit-field">
        <span class="edit-field__label">{{ t('shopping.itemCategory') }}</span>
        <input
          v-model="category"
          type="text"
          class="edit-field__input"
          list="category-suggestions"
          :placeholder="t('shopping.categoryPlaceholder')"
        />
        <datalist id="category-suggestions">
          <option v-for="cat in categories" :key="cat" :value="cat" />
        </datalist>
      </label>

      <!-- Actions -->
      <div class="edit-actions">
        <button type="button" class="btn-secondary" @click="emit('close')">
          {{ t('common.cancel') }}
        </button>
        <button type="submit" class="btn-primary" :disabled="!canSave">
          {{ t('common.save') }}
        </button>
      </div>
    </form>
  </BaseDialog>
</template>

<style scoped>
.edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.edit-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.edit-field__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
}

.edit-field__input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  transition: border-color var(--transition-fast);
}

.edit-field__input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

/* Store-Picker */
.store-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}

.store-pick-chip {
  display: flex;
  align-items: center;
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

.store-pick-chip--active {
  background: var(--ink);
  color: var(--card);
}

.store-pick-input {
  flex: 1;
  min-width: 120px;
  padding: 6px 12px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  min-height: 44px;
}

.store-pick-input:focus {
  outline: none;
  border-color: var(--acc);
  border-style: solid;
}

/* Actions */
.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
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
</style>
