<script setup lang="ts">
/**
 * Rezepte verwalten (P3): Liste, erstellen, bearbeiten, löschen.
 * Nutzt die bestehende Rezept-API über den food-Store. Bearbeiten sendet nur
 * geänderte Felder; Löschen behält geplante Mahlzeiten als Freitext (PD-M3).
 */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhBookOpen, PhPlus, PhStar } from '@phosphor-icons/vue'
import { useFoodStore } from '../stores/food'
import { useAsyncAction } from '../composables/useAsyncAction'
import { waitForOverlayBack } from '../composables/useBackClose'
import { formatRappen } from '../utils/money'
import {
  changedRecipeFields, emptyRecipeForm, formToPayload, recipeToForm,
  RECIPE_LIMITS, type RecipeForm, type RecipeFormError,
} from '../utils/recipeForm'
import type { Recipe } from '../types'
import BaseButton from './ui/BaseButton.vue'
import BaseCard from './ui/BaseCard.vue'
import BaseDialog from './ui/BaseDialog.vue'
import BaseInput from './ui/BaseInput.vue'

const foodStore = useFoodStore()
const { t } = useI18n()
const { run, isPending } = useAsyncAction()

const COLLAPSED_COUNT = 5
const showAll = ref(false)
const visibleRecipes = computed(() =>
  showAll.value ? foodStore.recipes : foodStore.recipes.slice(0, COLLAPSED_COUNT),
)

function recipeMeta(recipe: Recipe): string {
  const parts = [t('food.portions', { n: recipe.servings })]
  if (recipe.cost_rappen != null) parts.push(formatRappen(recipe.cost_rappen))
  if (recipe.duration_min != null) parts.push(t('food.minutes', { n: recipe.duration_min }))
  return parts.join(' · ')
}

// ── Formular ──
const formOpen = ref(false)
const editing = ref<Recipe | null>(null)
const form = ref<RecipeForm>(emptyRecipeForm())
const errors = ref<RecipeFormError[]>([])
const FORM_ID = 'recipe-form'

function openCreate() {
  editing.value = null
  form.value = emptyRecipeForm()
  errors.value = []
  formOpen.value = true
}

function openEdit(recipe: Recipe) {
  editing.value = recipe
  form.value = recipeToForm(recipe)
  errors.value = []
  formOpen.value = true
}

function closeForm() {
  formOpen.value = false
}

function errorFor(field: RecipeFormError): string | undefined {
  return errors.value.includes(field) ? t(`food.recipeError.${field}`) : undefined
}

async function save() {
  const result = formToPayload(form.value)
  if ('errors' in result) {
    errors.value = result.errors
    return
  }
  errors.value = []
  const original = editing.value
  if (original) {
    const changes = changedRecipeFields(original, result.payload)
    if (Object.keys(changes).length === 0) {
      closeForm()
      return
    }
    const ok = await run(() => foodStore.updateRecipe(original.id, changes), {
      key: 'recipe-save',
      success: t('food.recipeSaved'),
      error: t('food.recipeSaveError'),
    })
    if (ok) closeForm()
  } else {
    const ok = await run(() => foodStore.createRecipe(result.payload), {
      key: 'recipe-save',
      success: t('food.recipeCreated'),
      error: t('food.recipeSaveError'),
    })
    if (ok) closeForm()
  }
}

// ── Löschen (mit Rückfrage) ──
const deleteTarget = ref<Recipe | null>(null)

async function askDelete() {
  const recipe = editing.value
  if (!recipe) return
  closeForm()
  await nextTick()
  await waitForOverlayBack()
  deleteTarget.value = recipe
}

async function confirmDelete() {
  const recipe = deleteTarget.value
  if (!recipe) return
  const ok = await run(() => foodStore.deleteRecipe(recipe.id), {
    key: 'recipe-delete',
    success: t('food.recipeDeleted', { name: recipe.name }),
    error: t('food.recipeDeleteError'),
  })
  if (ok) deleteTarget.value = null
}

defineExpose({ openEdit, openCreate })
</script>

<template>
  <BaseCard>
    <template #header>
      <div class="recipes-header">
        <PhBookOpen :size="20" />
        <span>{{ t('food.recipes') }}</span>
        <BaseButton variant="ghost" size="sm" class="recipes-header__add" @click="openCreate">
          <PhPlus :size="16" weight="bold" />
          {{ t('food.newRecipe') }}
        </BaseButton>
      </div>
    </template>

    <p v-if="foodStore.recipes.length === 0" class="recipes-empty">{{ t('food.noRecipes') }}</p>
    <ul v-else class="recipe-list">
      <li v-for="recipe in visibleRecipes" :key="recipe.id">
        <button type="button" class="recipe-row tap-target" @click="openEdit(recipe)">
          <span class="recipe-row__name">
            {{ recipe.name }}
            <PhStar v-if="recipe.is_favorite" :size="14" weight="fill" class="recipe-row__fav" />
          </span>
          <span class="recipe-row__meta">{{ recipeMeta(recipe) }}</span>
        </button>
      </li>
    </ul>
    <BaseButton
      v-if="foodStore.recipes.length > COLLAPSED_COUNT"
      variant="ghost"
      size="sm"
      @click="showAll = !showAll"
    >
      {{ showAll ? t('food.showLess') : t('food.showAllRecipes', { n: foodStore.recipes.length }) }}
    </BaseButton>
  </BaseCard>

  <!-- ── Rezept erstellen / bearbeiten ── -->
  <BaseDialog
    :open="formOpen"
    :title="editing ? t('food.editRecipe') : t('food.newRecipe')"
    @close="closeForm"
  >
    <form :id="FORM_ID" class="recipe-form" novalidate @submit.prevent="save">
      <BaseInput
        id="recipe-name"
        v-model="form.name"
        :label="t('food.recipeName')"
        :error="errorFor('name')"
      />
      <div class="recipe-form__row">
        <BaseInput
          id="recipe-servings"
          v-model="form.servings"
          type="number"
          :label="t('food.servings')"
          :error="errorFor('servings')"
        />
        <BaseInput
          id="recipe-cost"
          v-model="form.cost"
          :label="t('food.costChf')"
          placeholder="0.00"
          :error="errorFor('cost')"
        />
        <BaseInput
          id="recipe-duration"
          v-model="form.duration"
          type="number"
          :label="t('food.durationMin')"
          :error="errorFor('duration')"
        />
      </div>

      <label class="recipe-form__label" for="recipe-ingredients">{{ t('food.ingredients') }}</label>
      <textarea
        id="recipe-ingredients"
        v-model="form.ingredients"
        class="recipe-form__textarea"
        rows="5"
        :placeholder="t('food.ingredientsPlaceholder')"
      />
      <p class="recipe-form__hint" :class="{ 'recipe-form__hint--error': errorFor('ingredients') }">
        {{ errorFor('ingredients') ?? t('food.onePerLine', { max: RECIPE_LIMITS.ingredients }) }}
      </p>

      <label class="recipe-form__label" for="recipe-steps">{{ t('food.steps') }}</label>
      <textarea
        id="recipe-steps"
        v-model="form.steps"
        class="recipe-form__textarea"
        rows="5"
        :placeholder="t('food.stepsPlaceholder')"
      />
      <p class="recipe-form__hint" :class="{ 'recipe-form__hint--error': errorFor('steps') }">
        {{ errorFor('steps') ?? t('food.onePerLine', { max: RECIPE_LIMITS.steps }) }}
      </p>

      <BaseInput
        id="recipe-tags"
        v-model="form.tags"
        :label="t('food.tags')"
        :placeholder="t('food.tagsPlaceholder')"
        :error="errorFor('tags')"
      />
    </form>

    <template #footer>
      <div class="recipe-actions">
        <BaseButton v-if="editing" variant="danger" size="sm" @click="askDelete">
          {{ t('food.deleteRecipe') }}
        </BaseButton>
        <div class="recipe-actions__spacer" />
        <BaseButton variant="secondary" size="sm" @click="closeForm">{{ t('food.cancel') }}</BaseButton>
        <BaseButton
          variant="primary"
          size="sm"
          type="submit"
          :form="FORM_ID"
          :loading="isPending('recipe-save')"
        >
          {{ t('food.save') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>

  <!-- ── Löschen bestätigen ── -->
  <BaseDialog
    :open="!!deleteTarget"
    :title="t('food.deleteRecipe')"
    danger
    @close="deleteTarget = null"
  >
    <p v-if="deleteTarget" class="recipe-delete__text">
      {{ t('food.confirmDelete', { name: deleteTarget.name }) }}
    </p>
    <p class="recipe-form__hint">{{ t('food.deleteRecipeHint') }}</p>
    <template #footer>
      <div class="recipe-actions">
        <div class="recipe-actions__spacer" />
        <BaseButton variant="secondary" size="sm" @click="deleteTarget = null">{{ t('food.cancel') }}</BaseButton>
        <BaseButton variant="danger" size="sm" :loading="isPending('recipe-delete')" @click="confirmDelete">
          {{ t('food.deleteRecipe') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>

<style scoped>
.recipes-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.recipes-header__add {
  margin-left: auto;
}

.recipes-empty {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
}

.recipe-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.recipe-row {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: var(--space-2) 0;
  border: none;
  border-bottom: 1px solid var(--line);
  background: none;
  text-align: left;
  cursor: pointer;
  color: var(--ink);
  font-family: var(--font-family);
}

.recipe-row__name {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: var(--font-weight-medium);
  overflow-wrap: anywhere;
}

.recipe-row__fav {
  color: var(--acc);
}

.recipe-row__meta {
  font-size: var(--text-xs);
  color: var(--sub);
}

.recipe-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.recipe-form__row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-2);
}

.recipe-form__label {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.recipe-form__textarea {
  width: 100%;
  box-sizing: border-box;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  font-family: var(--font-family);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--ink);
  resize: vertical;
}

.recipe-form__textarea:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 2px var(--acc-soft);
}

.recipe-form__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--sub);
}

.recipe-form__hint--error {
  color: var(--color-danger, var(--ink));
}

.recipe-delete__text {
  margin: 0 0 var(--space-2);
  color: var(--ink);
}

.recipe-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.recipe-actions__spacer {
  flex: 1;
}
</style>
