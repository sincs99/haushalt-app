<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useFoodStore } from '../stores/food'
import { usePollsStore } from '../stores/polls'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { waitForOverlayBack } from '../composables/useBackClose'
import { formatRappen } from '../utils/money'
import type { Recipe, MealPlanEntry, EventPoll, PollOption } from '../types'
import {
  PhCaretLeft, PhCaretRight, PhStar, PhShoppingBagOpen, PhForkKnife, PhPlus, PhTrash,
} from '@phosphor-icons/vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import AiRecipeCard from '../components/AiRecipeCard.vue'
import { useAiStore } from '../stores/ai'

const foodStore = useFoodStore()
const pollsStore = usePollsStore()
const authStore = useAuthStore()
const aiStore = useAiStore()
const router = useRouter()
const { on, off, onReconnect, offReconnect } = useSocket()
const { t, locale } = useI18n()
const { showToast, notifyError } = useToast()
const { run, isPending } = useAsyncAction()

const dateLocale = computed(() => (locale.value === 'en' ? 'en-GB' : 'de-CH'))

// ── Laden ──
const { loadError, reloading, reload } = useLoader(() => Promise.all([
  foodStore.fetchRecipes(),
  foodStore.fetchWeekPlan(),
  pollsStore.fetchPolls('offen'),
]))
/** Laden einer anderen Woche gescheitert (Wochenplan zeigt sonst die alte Woche als leer) */
const weekError = ref(false)
const showWeekError = computed(() => weekError.value || (loadError.value && foodStore.weekPlan.length === 0))

async function goWeek(direction: -1 | 1) {
  try {
    await foodStore.navigateWeek(direction)
    weekError.value = false
  } catch {
    weekError.value = true
  }
}

async function retryLoad() {
  await reload()
  if (!loadError.value) weekError.value = false
}

// ── Lifecycle ──
onMounted(() => {
  aiStore.fetchStatus()
  reload()

  on('recipe_created', handleRecipeCreated)
  on('recipe_updated', handleRecipeUpdated)
  on('recipe_deleted', handleRecipeDeleted)
  on('meal_plan_updated', handleMealPlanUpdated)
  on('meal_plan_deleted', handleMealPlanDeleted)
  onReconnect(handleReconnect)
})

onUnmounted(() => {
  off('recipe_created', handleRecipeCreated)
  off('recipe_updated', handleRecipeUpdated)
  off('recipe_deleted', handleRecipeDeleted)
  off('meal_plan_updated', handleMealPlanUpdated)
  off('meal_plan_deleted', handleMealPlanDeleted)
  offReconnect(handleReconnect)
})

// ── Socket-Handlers ──
function handleRecipeCreated(data: Recipe) { foodStore.handleRecipeCreated(data) }
function handleRecipeUpdated(data: Recipe) { foodStore.handleRecipeUpdated(data) }
function handleRecipeDeleted(data: { id: string }) { foodStore.handleRecipeDeleted(data) }
function handleMealPlanUpdated(data: MealPlanEntry) { foodStore.handleMealPlanUpdated(data) }
function handleMealPlanDeleted(data: { date: string }) { foodStore.handleMealPlanDeleted(data) }
function handleReconnect() {
  retryLoad()
}

// ── Kalenderwoche berechnen ──
function getISOWeek(dateStr: string): number {
  const d = new Date(dateStr + 'T00:00:00')
  d.setHours(0, 0, 0, 0)
  // Donnerstag der gleichen Woche
  d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7))
  const yearStart = new Date(d.getFullYear(), 0, 1)
  return Math.ceil((((d.getTime() - yearStart.getTime()) / 86400000) + 1) / 7)
}

const currentWeekNumber = computed(() => getISOWeek(foodStore.currentWeekStart))

// ── Wochentage als Array von Datums-Strings ──
const weekDates = computed(() => {
  const start = new Date(foodStore.currentWeekStart + 'T00:00:00')
  const dates: string[] = []
  for (let i = 0; i < 7; i++) {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    dates.push(`${y}-${m}-${day}`)
  }
  return dates
})

// ── Wochentag-Kürzel (sprachabhängig) ──
function getWeekdayLabel(dateStr: string): string {
  return new Date(dateStr + 'T00:00:00')
    .toLocaleDateString(dateLocale.value, { weekday: 'short' })
    .replace('.', '')
}

// ── Heute (YYYY-MM-DD) ──
const todayStr = computed(() => {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
})

// ── Hilfsfunktion: MealPlanEntry für ein Datum finden ──
function getEntryForDate(date: string): MealPlanEntry | undefined {
  return foodStore.weekPlan.find(e => e.date === date)
}

function getDisplayName(entry: MealPlanEntry | undefined): string {
  if (!entry) return t('food.noMeal')
  if (entry.recipe) return entry.recipe.name
  if (entry.free_text) return entry.free_text
  return t('food.noMeal')
}

function getMeta(entry: MealPlanEntry | undefined): string | null {
  if (!entry?.recipe) return null
  const parts: string[] = []
  if (entry.recipe.servings) {
    parts.push(t('food.portions', { n: entry.recipe.servings }))
  }
  if (entry.recipe.cost_rappen != null) {
    parts.push(formatRappen(entry.recipe.cost_rappen))
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

// ── Assign-Dialog ──
const showAssignDialog = ref(false)
const assignDate = ref('')
const assignRecipeId = ref<string | null>(null)
const assignFreeText = ref('')
const assignSaving = computed(() => isPending('assign') || isPending('removeMeal'))

function openAssignDialog(date: string) {
  const entry = getEntryForDate(date)
  assignDate.value = date
  assignRecipeId.value = entry?.recipe_id ?? null
  assignFreeText.value = entry?.free_text ?? ''
  showAssignDialog.value = true
}

async function doAssign() {
  const date = assignDate.value
  const payload = assignRecipeId.value
    ? { recipe_id: assignRecipeId.value, free_text: null }
    : { recipe_id: null, free_text: assignFreeText.value.trim() }
  if (!payload.recipe_id && !payload.free_text) return
  const ok = await run(() => foodStore.assignMeal(date, payload), {
    key: 'assign',
    error: t('food.assignError'),
  })
  if (ok) showAssignDialog.value = false
}

async function doRemoveMeal() {
  const date = assignDate.value
  const ok = await run(() => foodStore.removeMeal(date), {
    key: 'removeMeal',
    success: t('food.mealRemoved'),
    undo: (removed) => (removed ? foodStore.restoreMeal(removed) : undefined),
    error: t('food.removeError'),
  })
  if (ok) showAssignDialog.value = false
}

// ── Rezept-Detail-Dialog (bei Tap auf Tag mit Rezept) ──
const showDetailDialog = ref(false)
const detailEntry = ref<MealPlanEntry | null>(null)

function openDetailDialog(entry: MealPlanEntry) {
  detailEntry.value = entry
  showDetailDialog.value = true
}

function closeDetailDialog() {
  showDetailDialog.value = false
  detailEntry.value = null
}

/** Aus dem Detail-Dialog umbuchen: erst Detail schliessen, dann Zuweisen öffnen (kein Dialog über Dialog). */
async function switchToAssign() {
  const date = detailEntry.value?.date
  closeDetailDialog()
  if (!date) return
  await nextTick()
  await waitForOverlayBack()
  openAssignDialog(date)
}

async function doAddToShopping() {
  const entry = detailEntry.value
  if (!entry) return
  let addedText = ''
  const ok = await run(async () => {
    const result = await foodStore.addMissingToShopping(entry.id)
    if (!result) return
    addedText = t('ai.recipe.addedMissing', { n: result.added.length }, result.added.length)
    if (result.skipped.length > 0) {
      addedText += ` · ${t('food.skippedItems', { n: result.skipped.length })}`
    }
  }, { key: `shopping:${entry.id}`, error: t('food.addToShoppingError') })
  if (ok && addedText) {
    // Ergebnis liegt auf einer anderen Seite → Toast mit Link dorthin
    showToast(addedText, 'success', undefined, {
      label: t('food.goToShopping'),
      onAction: async () => {
        closeDetailDialog()
        await nextTick()
        router.push('/shopping')
      },
    })
  }
}

// ── Favoriten-Toggle ──
async function toggleFavorite(recipeId: string) {
  await run(() => foodStore.toggleFavorite(recipeId), {
    key: `fav:${recipeId}`,
    error: t('food.favoriteError'),
  })
}

// ── Zeile antippen: Assign oder Detail ──
function onRowClick(date: string) {
  const entry = getEntryForDate(date)
  if (entry?.recipe) {
    openDetailDialog(entry)
  } else {
    openAssignDialog(date)
  }
}

// ── Rezept-Dropdown: wenn gewählt, Freitext leeren ──
watch(assignRecipeId, (val) => {
  if (val) assignFreeText.value = ''
})

// ── Formatierung Datum-Tag ──
function getDayNumber(dateStr: string): string {
  return String(new Date(dateStr + 'T00:00:00').getDate())
}

// ── Assign-Dialog: Hat das Datum bereits einen Eintrag? ──
const assignHasEntry = computed(() => {
  return !!getEntryForDate(assignDate.value)
})

// ── Assign-Dialog: Formatierter Datum-String für den Titel ──
const assignDateFormatted = computed(() => {
  if (!assignDate.value) return ''
  const d = new Date(assignDate.value + 'T00:00:00')
  return d.toLocaleDateString(dateLocale.value, { weekday: 'long', day: 'numeric', month: 'long' })
})

// ── Meal-Polls ──
const todaysMealPolls = computed(() =>
  pollsStore.openMealPolls,
)

function hasVoted(poll: EventPoll, optionId: string): boolean {
  const userId = authStore.user?.id
  if (!userId) return false
  const option = poll.options.find(o => o.id === optionId)
  return option?.votes.some(v => v.user_id === userId) ?? false
}

async function vote(poll: EventPoll, optionId: string) {
  await run(() => pollsStore.votePoll(poll.id, optionId), {
    key: `vote:${poll.id}`,
    error: t('polls.voteError'),
  })
}

// ── Abstimmung entscheiden (mit Bestätigung) ──
const decidePollId = ref<string | null>(null)
// Immer die aktuelle Fassung aus dem Store (Stimmen können per Socket nachkommen);
// entscheidet jemand anderes zuerst, verschwindet die Abstimmung und der Dialog schliesst.
const decidePoll = computed(() => todaysMealPolls.value.find(p => p.id === decidePollId.value) ?? null)
const decideOptionId = ref<string | null>(null)

/** Optionen mit den meisten Stimmen (bei Gleichstand mehrere) */
const decideLeaders = computed<PollOption[]>(() => {
  const poll = decidePoll.value
  if (!poll || poll.options.length === 0) return []
  const max = Math.max(...poll.options.map(o => o.votes.length))
  return poll.options.filter(o => o.votes.length === max)
})
const decideIsTie = computed(() => decideLeaders.value.length > 1)
const decideOption = computed(() =>
  decidePoll.value?.options.find(o => o.id === decideOptionId.value) ?? null,
)

function openDecideDialog(poll: EventPoll) {
  decidePollId.value = poll.id
  // Bei eindeutigem Gewinner vorauswählen, bei Gleichstand wählt man selbst
  decideOptionId.value = decideLeaders.value.length === 1 ? decideLeaders.value[0].id : null
}

function closeDecideDialog() {
  decidePollId.value = null
  decideOptionId.value = null
}

async function confirmDecide() {
  const poll = decidePoll.value
  const option = decideOption.value
  if (!poll || !option) return
  const ok = await run(() => pollsStore.mealDecidePoll(poll.id, option.id), {
    key: `decide:${poll.id}`,
    success: t('food.pollDecidedToast', { option: option.label }),
    error: t('polls.decideError'),
  })
  if (!ok) return
  closeDecideDialog()
  // Wochenplan neu laden (Ergebnis erscheint dort)
  foodStore.fetchWeekPlan().catch((err) => notifyError(t('common.loadError'), err))
}

// ── Create Meal Poll Dialog ──
const showCreateMealPoll = ref(false)
const newPollQuestion = ref('')
const newPollDate = ref('')
const newPollOptions = ref<Array<{ label: string; recipe_id?: string }>>([
  { label: '' },
  { label: '' },
])

function openCreateMealPoll() {
  newPollQuestion.value = t('food.pollQuestionDefault')
  newPollDate.value = todayStr.value
  newPollOptions.value = [{ label: '' }, { label: '' }]
  showCreateMealPoll.value = true
}

function addPollOption() {
  newPollOptions.value.push({ label: '' })
}

function removePollOption(idx: number) {
  if (newPollOptions.value.length > 2) {
    newPollOptions.value.splice(idx, 1)
  }
}

function setOptionFromRecipe(idx: number, recipeId: string) {
  const recipe = foodStore.recipes.find(r => r.id === recipeId)
  if (recipe) {
    newPollOptions.value[idx] = { label: recipe.name, recipe_id: recipe.id }
  }
}

const canCreatePoll = computed(() => {
  const filledOptions = newPollOptions.value.filter(o => o.label.trim())
  return newPollQuestion.value.trim() && filledOptions.length >= 2
})

async function doCreateMealPoll() {
  if (!canCreatePoll.value) return
  const validOptions = newPollOptions.value.filter(o => o.label.trim())
  const ok = await run(() => pollsStore.createMealPoll(
    newPollQuestion.value.trim(),
    newPollDate.value,
    validOptions,
  ), { key: 'createPoll', error: t('food.createPollError') })
  if (ok) showCreateMealPoll.value = false
}
</script>

<template>
  <div class="food-view">
    <!-- Header mit Wochennavigation -->
    <PageHeader :title="t('food.title')">
      <template #actions>
        <div class="week-nav">
          <button type="button" class="week-nav__btn tap-target" @click="goWeek(-1)" :aria-label="t('food.prevWeek')">
            <PhCaretLeft :size="20" weight="bold" />
          </button>
          <span class="week-nav__label">{{ t('food.kwLabel', { week: currentWeekNumber }) }}</span>
          <button type="button" class="week-nav__btn tap-target" @click="goWeek(1)" :aria-label="t('food.nextWeek')">
            <PhCaretRight :size="20" weight="bold" />
          </button>
        </div>
      </template>
    </PageHeader>

    <!-- Wochenmenü-Karte -->
    <BaseCard>
      <template #default>
        <h3 class="card-section-title">{{ t('food.weekMenu') }}</h3>

        <!-- Skeleton während Laden -->
        <div v-if="foodStore.loading || (reloading && foodStore.weekPlan.length === 0)" class="week-skeleton">
          <BaseSkeleton v-for="i in 7" :key="i" height="48px" style="margin-bottom: var(--space-2)" />
        </div>

        <!-- Ladefehler (sonst sähe die Woche leer aus) -->
        <BaseErrorState v-else-if="showWeekError" :retrying="reloading" @retry="retryLoad" />

        <!-- Wochentage -->
        <ul v-else class="week-list">
          <li
            v-for="date in weekDates"
            :key="date"
            class="week-row"
            role="button"
            tabindex="0"
            @click="onRowClick(date)"
            @keydown.enter.self.prevent="onRowClick(date)"
            @keydown.space.self.prevent="onRowClick(date)"
          >
            <!-- Tageszahl mit Ring wenn heute -->
            <span
              class="week-row__day-num"
              :class="{ 'week-row__day-num--today': date === todayStr }"
            >
              {{ getDayNumber(date) }}
            </span>

            <!-- Wochentag-Kürzel -->
            <span class="week-row__weekday">{{ getWeekdayLabel(date) }}</span>

            <!-- Gerichtsinfo -->
            <div class="week-row__meal">
              <span
                class="week-row__name"
                :class="{ 'week-row__name--empty': !getEntryForDate(date) }"
              >
                {{ getDisplayName(getEntryForDate(date)) }}
              </span>
              <span v-if="getMeta(getEntryForDate(date))" class="week-row__meta">
                {{ getMeta(getEntryForDate(date)) }}
              </span>
            </div>

            <!-- Favoriten-Stern -->
            <button
              v-if="getEntryForDate(date)?.recipe"
              type="button"
              class="week-row__fav tap-target"
              :class="{ 'week-row__fav--active': getEntryForDate(date)?.recipe?.is_favorite }"
              @click.stop="toggleFavorite(getEntryForDate(date)!.recipe!.id)"
              @keydown.enter.stop
              @keydown.space.stop
              :aria-label="t('food.favorite')"
              :aria-pressed="!!getEntryForDate(date)?.recipe?.is_favorite"
            >
              <PhStar
                :size="20"
                :weight="getEntryForDate(date)?.recipe?.is_favorite ? 'fill' : 'regular'"
              />
            </button>
            <span v-else class="week-row__fav-spacer" />
          </li>
        </ul>
      </template>
    </BaseCard>

    <!-- ── Karte: Was essen wir heute? ── -->
    <BaseCard v-if="todaysMealPolls.length > 0 || todaysMealPolls.length === 0">
      <template #header>
        <div class="card-header">
          <PhForkKnife :size="20" />
          <span>{{ t('food.whatToEat') }}</span>
        </div>
      </template>

      <!-- Offene Meal-Polls anzeigen -->
      <div v-for="poll in todaysMealPolls" :key="poll.id" class="meal-poll">
        <h4 class="meal-poll__question">{{ poll.question }}</h4>
        <div class="meal-poll__options">
          <button
            v-for="option in poll.options"
            :key="option.id"
            type="button"
            class="meal-poll__option"
            :class="{ 'meal-poll__option--voted': hasVoted(poll, option.id) }"
            :aria-pressed="hasVoted(poll, option.id)"
            :disabled="isPending(`vote:${poll.id}`)"
            @click="vote(poll, option.id)"
          >
            <span class="meal-poll__option-label">{{ option.label }}</span>
            <span class="meal-poll__option-count">{{ option.votes.length }}</span>
          </button>
        </div>
        <!-- Entscheiden-Button (wenn mindestens eine Stimme) -->
        <BaseButton
          v-if="poll.options.some(o => o.votes.length > 0)"
          size="sm"
          variant="primary"
          :loading="isPending(`decide:${poll.id}`)"
          @click="openDecideDialog(poll)"
          class="meal-poll__decide"
        >
          {{ t('food.decidePoll') }}
        </BaseButton>
      </div>

      <!-- Keine offenen Polls → Erstellen-Button -->
      <BaseButton
        v-if="todaysMealPolls.length === 0"
        variant="outline"
        @click="openCreateMealPoll"
      >
        {{ t('food.createPoll') }}
      </BaseButton>

      <!-- Falls Polls existieren, aber man noch eine starten will -->
      <BaseButton
        v-if="todaysMealPolls.length > 0"
        variant="ghost"
        size="sm"
        @click="openCreateMealPoll"
        class="meal-poll__add-more"
      >
        {{ t('food.createPoll') }}
      </BaseButton>
    </BaseCard>

    <!-- ── KI-Rezeptvorschlag (nur mit Server-Schlüssel und Opt-in des Haushalts) ── -->
    <AiRecipeCard v-if="aiStore.enabledForHousehold" />

    <!-- ── Create Meal Poll Dialog ── -->
    <BaseDialog
      :open="showCreateMealPoll"
      :title="t('food.whatToEat')"
      @close="showCreateMealPoll = false"
    >
      <form id="meal-poll-form" class="poll-form" @submit.prevent="doCreateMealPoll">
        <label class="poll-form__label" for="meal-poll-question">{{ t('food.pollQuestion') }}</label>
        <BaseInput
          id="meal-poll-question"
          v-model="newPollQuestion"
          :placeholder="t('food.pollQuestionDefault')"
        />

        <label class="poll-form__label poll-form__label--mt">{{ t('polls.option') }}</label>
        <div
          v-for="(opt, idx) in newPollOptions"
          :key="idx"
          class="poll-form__option-row"
        >
          <BaseInput
            v-model="newPollOptions[idx].label"
            :placeholder="`${t('polls.option')} ${idx + 1}`"
            class="poll-form__option-input"
          />
          <select
            class="poll-form__recipe-select"
            :aria-label="t('food.selectRecipe')"
            @change="(e: Event) => { const val = (e.target as HTMLSelectElement).value; if (val) setOptionFromRecipe(idx, val) }"
          >
            <option value="">{{ t('food.selectRecipe') }}</option>
            <option
              v-for="recipe in foodStore.recipes"
              :key="recipe.id"
              :value="recipe.id"
            >
              {{ recipe.name }}
            </option>
          </select>
          <button
            v-if="newPollOptions.length > 2"
            type="button"
            class="poll-form__remove-btn"
            :aria-label="t('food.removeOption')"
            @click="removePollOption(idx)"
          >
            <PhTrash :size="16" />
          </button>
        </div>

        <button type="button" class="poll-form__add-btn tap-target" @click="addPollOption">
          <PhPlus :size="16" />
          {{ t('food.addOption') }}
        </button>

        <p v-if="!canCreatePoll" class="poll-form__hint">
          {{ t('food.minTwoOptions') }}
        </p>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="secondary" size="sm" @click="showCreateMealPoll = false">
            {{ t('food.cancel') }}
          </BaseButton>
          <div class="dialog-actions__spacer" />
          <BaseButton
            variant="primary"
            size="sm"
            type="submit"
            form="meal-poll-form"
            :disabled="!canCreatePoll"
            :loading="isPending('createPoll')"
          >
            {{ t('food.startPoll') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ── Zuweisen-Dialog ── -->
    <BaseDialog
      :open="showAssignDialog"
      :title="`${t('food.assignTitle')} — ${assignDateFormatted}`"
      @close="showAssignDialog = false"
    >
      <form id="meal-assign-form" class="assign-form" @submit.prevent="doAssign">
        <!-- Rezept-Auswahl -->
        <label class="assign-form__label" for="meal-assign-recipe">{{ t('food.selectRecipe') }}</label>
        <select
          id="meal-assign-recipe"
          v-model="assignRecipeId"
          class="assign-form__select"
        >
          <option :value="null">—</option>
          <option
            v-for="recipe in foodStore.recipes"
            :key="recipe.id"
            :value="recipe.id"
          >
            {{ recipe.name }}
            <template v-if="recipe.is_favorite"> ★</template>
          </option>
        </select>

        <!-- Freitext-Alternative -->
        <label class="assign-form__label assign-form__label--or" for="meal-assign-free">{{ t('food.freeText') }}</label>
        <BaseInput
          id="meal-assign-free"
          v-model="assignFreeText"
          :placeholder="t('food.freeText')"
          :disabled="!!assignRecipeId"
        />
      </form>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton
            v-if="assignHasEntry"
            variant="danger"
            size="sm"
            :loading="isPending('removeMeal')"
            :disabled="assignSaving"
            @click="doRemoveMeal"
          >
            {{ t('food.remove') }}
          </BaseButton>
          <div class="dialog-actions__spacer" />
          <BaseButton
            variant="secondary"
            size="sm"
            @click="showAssignDialog = false"
          >
            {{ t('food.cancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            size="sm"
            type="submit"
            form="meal-assign-form"
            :loading="isPending('assign')"
            :disabled="assignSaving || (!assignRecipeId && !assignFreeText.trim())"
          >
            {{ t('food.assign') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ── Rezept-Detail-Dialog ── -->
    <BaseDialog
      :open="showDetailDialog"
      :title="detailEntry?.recipe?.name ?? ''"
      @close="closeDetailDialog"
    >
      <div v-if="detailEntry?.recipe" class="detail-content">
        <!-- Meta-Info -->
        <div class="detail-meta" v-if="getMeta(detailEntry)">
          {{ getMeta(detailEntry) }}
        </div>

        <!-- Zutaten-Liste -->
        <div v-if="detailEntry.recipe.ingredients.length > 0" class="detail-ingredients">
          <h4 class="detail-ingredients__title">{{ t('food.ingredients') }}</h4>
          <ul class="detail-ingredients__list">
            <li
              v-for="(ingredient, idx) in detailEntry.recipe.ingredients"
              :key="idx"
              class="detail-ingredients__item"
            >
              {{ ingredient }}
            </li>
          </ul>
        </div>

        <!-- Zubereitung -->
        <div v-if="detailEntry.recipe.steps?.length" class="detail-ingredients">
          <h4 class="detail-ingredients__title">{{ t('food.steps') }}</h4>
          <ol class="detail-steps">
            <li v-for="(step, idx) in detailEntry.recipe.steps" :key="idx">{{ step }}</li>
          </ol>
        </div>

        <!-- Zur Einkaufsliste hinzufügen -->
        <div class="detail-shopping">
          <BaseButton
            variant="secondary"
            :loading="isPending(`shopping:${detailEntry.id}`)"
            @click="doAddToShopping"
          >
            <PhShoppingBagOpen :size="20" style="margin-right: var(--space-1-5)" />
            {{ t('food.addToShopping') }}
          </BaseButton>
        </div>
      </div>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="secondary" size="sm" @click="switchToAssign">
            {{ t('food.assignTitle') }}
          </BaseButton>
          <div class="dialog-actions__spacer" />
          <BaseButton variant="ghost" size="sm" @click="closeDetailDialog">
            {{ t('common.close') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ── Abstimmung entscheiden: Bestätigung mit Gewinner ── -->
    <BaseDialog
      :open="!!decidePoll"
      :title="t('food.decideTitle')"
      @close="closeDecideDialog"
    >
      <div v-if="decidePoll" class="decide-content">
        <p class="decide-content__question">{{ decidePoll.question }}</p>

        <!-- Gleichstand: selbst wählen -->
        <template v-if="decideIsTie">
          <p class="decide-content__text">{{ t('food.decideTie') }}</p>
          <div class="decide-content__options" role="radiogroup" :aria-label="t('food.decideTitle')">
            <label
              v-for="option in decideLeaders"
              :key="option.id"
              class="decide-content__option"
            >
              <input v-model="decideOptionId" type="radio" name="decide-option" :value="option.id" />
              <span>{{ option.label }}</span>
              <span class="decide-content__votes">{{ t('food.voteCount', { n: option.votes.length }, option.votes.length) }}</span>
            </label>
          </div>
        </template>

        <p v-else-if="decideOption" class="decide-content__text">
          {{ t('food.decideWinner', { option: decideOption.label, n: decideOption.votes.length }, decideOption.votes.length) }}
        </p>

        <p class="decide-content__hint">{{ t('food.decideHint') }}</p>
      </div>

      <template #footer>
        <div class="dialog-actions">
          <div class="dialog-actions__spacer" />
          <BaseButton variant="secondary" size="sm" @click="closeDecideDialog">
            {{ t('food.cancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            size="sm"
            :disabled="!decideOption"
            :loading="!!decidePoll && isPending(`decide:${decidePoll.id}`)"
            @click="confirmDecide"
          >
            {{ t('food.decidePoll') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.food-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-width: 600px;
  margin: 0 auto;
}

/* ── Week Navigation ── */
.week-nav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.week-nav__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--chip);
  color: var(--ink);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.week-nav__btn:hover {
  background: var(--line);
}

.week-nav__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  min-width: 56px;
  text-align: center;
}

/* ── Card Section Title ── */
.card-section-title {
  margin: 0 0 var(--space-3);
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

/* ── Week List ── */
.week-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.week-row:focus-visible {
  outline: 2px solid var(--acc);
  outline-offset: 2px;
}

.week-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  cursor: pointer;
  border-bottom: 1px solid var(--line);
  transition: background var(--transition-fast);
}

.week-row:last-child {
  border-bottom: none;
}

.week-row:hover {
  background: var(--chip);
  margin: 0 calc(-1 * var(--space-3));
  padding-left: var(--space-3);
  padding-right: var(--space-3);
  border-radius: var(--radius-sm);
}

/* ── Day Number ── */
.week-row__day-num {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  flex-shrink: 0;
  border-radius: var(--radius-full);
}

.week-row__day-num--today {
  border: 2px solid var(--acc);
  color: var(--acc);
}

/* ── Weekday ── */
.week-row__weekday {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  /* 3 Grossbuchstaben (EN „WED“, „THU“) brauchen ~29 px */
  width: var(--space-8);
  flex-shrink: 0;
  text-transform: uppercase;
}

/* ── Meal Info ── */
.week-row__meal {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.week-row__name {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.week-row__name--empty {
  color: var(--sub);
  font-style: italic;
  font-weight: var(--font-weight-normal);
}

.week-row__meta {
  font-size: var(--text-xs);
  color: var(--sub);
}

/* ── Favorite Star ── */
.week-row__fav {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  color: var(--sub);
  cursor: pointer;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  transition: color var(--transition-fast);
}

.week-row__fav:hover {
  color: var(--acc);
}

.week-row__fav--active {
  color: var(--acc);
}

.week-row__fav-spacer {
  width: 32px;
  flex-shrink: 0;
}

/* ── Skeleton ── */
.week-skeleton {
  display: flex;
  flex-direction: column;
}

/* ── Assign Form ── */
.assign-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.assign-form__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.assign-form__label--or {
  margin-top: var(--space-3);
}

.assign-form__select {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--ink);
  appearance: auto;
  cursor: pointer;
}

.assign-form__select:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 2px var(--acc-soft);
}

/* ── Dialog Actions ── */
.dialog-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.dialog-actions__spacer {
  flex: 1;
}

/* ── Detail Content ── */
.detail-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.detail-meta {
  font-size: var(--text-sm);
  color: var(--sub);
}

/* ── Ingredients ── */
.detail-ingredients__title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.detail-ingredients__list {
  margin: 0;
  padding: 0 0 0 var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.detail-ingredients__item {
  font-size: var(--text-sm);
  color: var(--ink);
}

/* ── Shopping Button Result ── */
.detail-steps {
  margin: 0;
  padding-left: var(--space-4);
  font-size: var(--text-sm);
  line-height: var(--line-height-normal);
  color: var(--ink);
}

.detail-steps li + li {
  margin-top: var(--space-1);
}

.detail-shopping {
  margin-top: var(--space-2);
}

/* ── Abstimmung entscheiden ── */
.decide-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.decide-content__question {
  margin: 0;
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.decide-content__text {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink);
}

.decide-content__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--sub);
}

.decide-content__options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.decide-content__option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--ink);
  cursor: pointer;
}

.decide-content__votes {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--sub);
}

/* ── Card Header ── */
.card-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

/* ── Meal Poll ── */
.meal-poll {
  margin-bottom: var(--space-4);
}

.meal-poll:last-of-type {
  margin-bottom: var(--space-3);
}

.meal-poll__question {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.meal-poll__options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.meal-poll__option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--ink);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: var(--text-sm);
}

.meal-poll__option:hover {
  border-color: var(--acc);
  background: var(--acc-soft);
}

.meal-poll__option--voted {
  border-color: var(--acc);
  background: var(--acc-soft);
  font-weight: var(--font-weight-semibold);
}

.meal-poll__option-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meal-poll__option-count {
  flex-shrink: 0;
  min-width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--chip);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-bold);
  color: var(--ink);
}

.meal-poll__option--voted .meal-poll__option-count {
  background: var(--acc);
  color: var(--color-on-accent);
}

.meal-poll__decide {
  margin-top: var(--space-1);
}

.meal-poll__add-more {
  margin-top: var(--space-2);
}

/* ── Poll Form (Create Dialog) ── */
.poll-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.poll-form__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.poll-form__label--mt {
  margin-top: var(--space-2);
}

.poll-form__option-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.poll-form__option-input {
  flex: 1;
}

.poll-form__recipe-select {
  width: 140px;
  padding: var(--space-2);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--ink);
  flex-shrink: 0;
}

.poll-form__remove-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  color: var(--sub);
  cursor: pointer;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  transition: color var(--transition-fast);
}

.poll-form__remove-btn:hover {
  color: var(--color-danger);
}

.poll-form__add-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) 0;
  margin-top: var(--space-1); /* Tap-Fläche nicht über dem Eingabefeld */
  font-size: var(--text-sm);
  color: var(--acc);
  background: none;
  border: none;
  cursor: pointer;
  font-weight: var(--font-weight-medium);
}

.poll-form__add-btn:hover {
  text-decoration: underline;
}

.poll-form__hint {
  font-size: var(--text-xs);
  color: var(--sub);
  margin: 0;
}
</style>
