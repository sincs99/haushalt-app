<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhSparkle, PhShoppingBagOpen } from '@phosphor-icons/vue'
import { useAiStore } from '../stores/ai'
import { useToast } from '../composables/useToast'
import { translateApiError } from '../utils/apiErrors'
import type { AiRecipePreference } from '../types'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseInput from './ui/BaseInput.vue'

/**
 * KI-Rezeptvorschlag: Zutaten rein, Vorschlag zur Prüfung raus.
 * Gespeichert wird erst auf Knopfdruck über den normalen Rezept-Endpunkt.
 */
const aiStore = useAiStore()
const { t } = useI18n()
const { showToast } = useToast()

const PREFERENCES: AiRecipePreference[] = ['vegetarian', 'quick', 'kids', 'leftovers']

const ingredientsText = ref('')
const servings = ref(2)
const preferences = ref<AiRecipePreference[]>([])
const note = ref('')
const saving = ref(false)
const saved = ref(false)
const addingMissing = ref(false)
const missingAdded = ref<number | null>(null)

const ingredients = computed(() =>
  ingredientsText.value.split(/[,\n;]/).map(s => s.trim()).filter(Boolean),
)

const suggestion = computed(() => aiStore.recipeSuggestion)

function togglePreference(p: AiRecipePreference) {
  preferences.value = preferences.value.includes(p)
    ? preferences.value.filter(x => x !== p)
    : [...preferences.value, p]
}

async function generate() {
  if (ingredients.value.length === 0) return
  saved.value = false
  missingAdded.value = null
  await aiStore.suggestRecipe({
    ingredients: ingredients.value.slice(0, 30),
    servings: servings.value,
    preferences: preferences.value,
    note: note.value,
  })
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    await aiStore.saveSuggestedRecipe()
    saved.value = true
    showToast(t('ai.recipe.saved'), 'success')
  } catch (error) {
    showToast(translateApiError(error), 'error')
  } finally {
    saving.value = false
  }
}

async function addMissing() {
  if (!suggestion.value || addingMissing.value) return
  addingMissing.value = true
  try {
    missingAdded.value = await aiStore.addMissingToShopping(suggestion.value.missing_ingredients)
  } catch (error) {
    showToast(translateApiError(error), 'error')
  } finally {
    addingMissing.value = false
  }
}

function discard() {
  aiStore.clearRecipe()
  saved.value = false
  missingAdded.value = null
}
</script>

<template>
  <BaseCard>
    <h3 class="ai-card__header">
      <PhSparkle :size="20" />
      <span>{{ t('ai.recipe.title') }}</span>
    </h3>

    <!-- Eingabe -->
    <form v-if="!suggestion" class="ai-form" @submit.prevent="generate">
      <label class="ai-form__label" for="ai-ingredients">{{ t('ai.recipe.ingredientsLabel') }}</label>
      <textarea
        id="ai-ingredients"
        v-model="ingredientsText"
        class="ai-form__textarea"
        rows="3"
        maxlength="2000"
        :placeholder="t('ai.recipe.ingredientsPlaceholder')"
      />
      <p class="ai-form__hint">{{ t('ai.recipe.ingredientsHint') }}</p>

      <div class="ai-form__row">
        <label class="ai-form__label" for="ai-servings">{{ t('ai.recipe.servings') }}</label>
        <input
          id="ai-servings"
          v-model.number="servings"
          class="ai-form__number"
          type="number"
          min="1"
          max="20"
        />
      </div>

      <div class="ai-chips" role="group" :aria-label="t('ai.recipe.preferencesLabel')">
        <button
          v-for="p in PREFERENCES"
          :key="p"
          type="button"
          class="ai-chip"
          :class="{ 'ai-chip--active': preferences.includes(p) }"
          :aria-pressed="preferences.includes(p)"
          @click="togglePreference(p)"
        >
          {{ t(`ai.recipe.preferences.${p}`) }}
        </button>
      </div>

      <BaseInput v-model="note" :label="t('ai.recipe.noteLabel')" maxlength="200" />

      <p v-if="aiStore.recipeError" class="ai-error" role="alert">
        {{ t(`errors.${aiStore.recipeError}`) }}
      </p>

      <BaseButton
        type="submit"
        :loading="aiStore.recipeLoading"
        :disabled="ingredients.length === 0 || aiStore.recipeLoading"
      >
        {{ aiStore.recipeLoading ? t('ai.recipe.generating') : t('ai.recipe.generate') }}
      </BaseButton>
    </form>

    <!-- Vorschlag zur Prüfung -->
    <div v-else class="ai-result">
      <p class="ai-result__review">{{ t('ai.recipe.reviewHint') }}</p>
      <h3 class="ai-result__name">{{ suggestion.recipe.name }}</h3>
      <p class="ai-result__meta">
        {{ t('food.portions', { n: suggestion.recipe.servings }) }}
        <template v-if="suggestion.recipe.duration_min">
          · {{ t('ai.recipe.duration', { n: suggestion.recipe.duration_min }) }}
        </template>
      </p>
      <div v-if="suggestion.recipe.tags.length" class="ai-tags">
        <span v-for="tag in suggestion.recipe.tags" :key="tag" class="ai-tag">{{ tag }}</span>
      </div>

      <h4 class="ai-result__title">{{ t('food.ingredients') }}</h4>
      <ul class="ai-result__list">
        <li v-for="(item, idx) in suggestion.recipe.ingredients" :key="idx">{{ item }}</li>
      </ul>

      <h4 class="ai-result__title">{{ t('food.steps') }}</h4>
      <ol class="ai-result__steps">
        <li v-for="(step, idx) in suggestion.recipe.steps" :key="idx">{{ step }}</li>
      </ol>

      <p v-if="suggestion.tip" class="ai-result__tip">
        <strong>{{ t('ai.recipe.tip') }}:</strong> {{ suggestion.tip }}
      </p>

      <div v-if="suggestion.missing_ingredients.length" class="ai-missing">
        <h4 class="ai-result__title">{{ t('ai.recipe.missing') }}</h4>
        <ul class="ai-result__list">
          <li v-for="(item, idx) in suggestion.missing_ingredients" :key="idx">
            {{ item.quantity ? `${item.quantity} ${item.name}` : item.name }}
          </li>
        </ul>
        <p v-if="missingAdded !== null" class="ai-success">
          {{ t('ai.recipe.addedMissing', { n: missingAdded }, missingAdded) }}
        </p>
        <BaseButton v-else variant="secondary" size="sm" :loading="addingMissing" @click="addMissing">
          <PhShoppingBagOpen :size="16" style="margin-right: var(--space-1-5)" />
          {{ t('ai.recipe.addMissing') }}
        </BaseButton>
      </div>

      <p class="ai-disclaimer">{{ t('ai.disclaimer') }}</p>

      <div class="ai-actions">
        <BaseButton variant="ghost" size="sm" @click="discard">
          {{ saved ? t('ai.recipe.newSuggestion') : t('ai.recipe.discard') }}
        </BaseButton>
        <div class="ai-actions__spacer" />
        <BaseButton size="sm" :loading="saving" :disabled="saved" @click="save">
          {{ saved ? t('ai.recipe.saved') : t('ai.recipe.save') }}
        </BaseButton>
      </div>
    </div>
  </BaseCard>
</template>

<style scoped>
.ai-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  font-size: var(--text-base);
  font-family: var(--font-display);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.ai-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ai-form__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.ai-form__textarea,
.ai-form__number {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-btn);
  background: var(--card);
  color: var(--ink);
  font: inherit;
  font-size: var(--text-base); /* iOS-Zoom vermeiden */
  box-sizing: border-box;
}

.ai-form__textarea {
  resize: vertical;
}

.ai-form__number {
  width: 80px;
}

.ai-form__hint {
  margin: calc(-1 * var(--space-2)) 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ai-form__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.ai-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ai-chip {
  min-height: 36px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-full);
  background: var(--chip);
  color: var(--ink);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
}

.ai-chip--active {
  background: var(--ink);
  color: var(--card);
}

.ai-error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.ai-success {
  margin: 0;
  color: var(--ok);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
}

.ai-result {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.ai-result__review {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-btn);
  background: var(--chip);
  font-size: var(--text-sm);
  color: var(--ink);
}

.ai-result__name {
  margin: var(--space-2) 0 0;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  color: var(--ink);
}

.ai-result__meta {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.ai-result__title {
  margin: var(--space-3) 0 var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.ai-result__list,
.ai-result__steps {
  margin: 0;
  padding-left: var(--space-4);
  color: var(--ink);
  font-size: var(--text-sm);
  line-height: var(--line-height-normal);
}

.ai-result__steps li + li {
  margin-top: var(--space-1);
}

.ai-result__tip {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--ink);
}

.ai-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.ai-tag {
  padding: var(--space-0-5) var(--space-2);
  border-radius: var(--radius-full);
  background: var(--chip);
  font-size: var(--text-xs);
  color: var(--ink);
}

.ai-missing {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.ai-disclaimer {
  margin: var(--space-2) 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ai-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.ai-actions__spacer {
  flex: 1;
}
</style>
