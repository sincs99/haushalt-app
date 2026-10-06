<script setup lang="ts">
/**
 * Ziel der Chip-/QR-URL /t/:token.
 *
 * Login erzwingt der Router-Guard (redirect zurück hierher). Danach:
 * resolve → bei *.open direkt navigieren, sonst Bestätigung mit einem
 * grossen Button; erst der Tipp ruft execute auf.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useTagsStore } from '../stores/tags'
import { formatDateShort } from '../utils/dates'
import {
  moduleRouteFor,
  nextScanStep,
  plantWaterLines,
  scanErrorKind,
  suggestedSlot,
  type ScanErrorKind,
} from '../utils/tagScan'
import type { TagExecuteResult, TagResolveResult } from '../types'

import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseSpinner from '../components/ui/BaseSpinner.vue'
import { PhCheckCircle, PhWarningCircle, PhQrCode } from '@phosphor-icons/vue'

const route = useRoute()
const router = useRouter()
const { t, te } = useI18n()
const authStore = useAuthStore()
const store = useTagsStore()

type State = 'loading' | 'confirm' | 'blocked' | 'executing' | 'done' | 'error'

const state = ref<State>('loading')
const result = ref<TagResolveResult | null>(null)
const execResult = ref<TagExecuteResult | null>(null)
const errorKind = ref<ScanErrorKind>('unknown')
const blockedReason = ref<string>('UNKNOWN')
const slot = ref<'morning' | 'evening'>('morning')
const switchHouseholdTo = ref<string | null>(null)

const token = computed(() => String(route.params.token ?? ''))

function actionText(suffix: string, params: Record<string, unknown> = {}): string {
  const key = `tags.actions.${result.value?.action}.${suffix}`
  return te(key) ? t(key, params) : result.value?.description ?? ''
}

const title = computed(() => {
  const r = result.value
  if (!r) return ''
  if ((r.action === 'pet.feed' || r.action === 'plant.water') && !r.target_name) return actionText('confirmAll')
  return actionText('confirm', { name: r.target_name ?? r.label })
})

const showHousehold = computed(() => authStore.households.length > 1)

function formatWhen(iso: string): string {
  const time = new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return `${formatDateShort(iso)} ${time}`
}

/** Detailzeilen der Bestätigungsseite je Aktion. */
const detailLines = computed<string[]>(() => {
  const r = result.value
  if (!r) return []
  const d = r.details ?? {}
  const lines: string[] = []
  switch (r.action) {
    case 'pet.feed': {
      if (d.last_fed_at) {
        lines.push(
          d.last_fed_by
            ? t('tags.scan.lastFedBy', { when: formatWhen(d.last_fed_at), name: d.last_fed_by })
            : t('tags.scan.lastFed', { when: formatWhen(d.last_fed_at) }),
        )
      } else {
        lines.push(t('tags.scan.neverFed'))
      }
      for (const pet of (d.pets ?? []) as { name: string; morning_fed: boolean; evening_fed: boolean }[]) {
        const status = t('tags.scan.fedToday', {
          morning: pet.morning_fed ? '✓' : '–',
          evening: pet.evening_fed ? '✓' : '–',
        })
        lines.push(r.target_name ? status : `${pet.name}: ${status}`)
      }
      break
    }
    case 'pet.care_task.done':
      if (d.pet_name) lines.push(t('tags.scan.pet', { name: d.pet_name }))
      if (d.next_due_at) lines.push(t('tags.scan.nextDue', { date: formatDateShort(d.next_due_at) }))
      if (d.last_done_at) lines.push(t('tags.scan.lastDone', { date: formatDateShort(d.last_done_at) }))
      break
    case 'plant.water':
      for (const line of plantWaterLines(d, !!r.target_name)) {
        if (line.kind === 'neverWatered') lines.push(t('tags.scan.neverWatered'))
        else if (line.kind === 'dueCount') lines.push(t('tags.scan.dueCount', { n: line.value }))
        else if (line.kind === 'lastWatered') lines.push(t('tags.scan.lastWatered', { date: formatDateShort(String(line.value)) }))
        else lines.push(t('tags.scan.plantDue', { date: formatDateShort(String(line.value)) }))
      }
      break
    case 'plant.care_task.done':
      if (d.plant_name) lines.push(t('tags.scan.plant', { name: d.plant_name }))
      if (d.next_due_at) lines.push(t('tags.scan.nextDue', { date: formatDateShort(d.next_due_at) }))
      if (d.last_done_at) lines.push(t('tags.scan.lastDone', { date: formatDateShort(d.last_done_at) }))
      break
    case 'chore.assignment.done':
      if (d.due_date) lines.push(t('tags.scan.dueDate', { date: formatDateShort(d.due_date) }))
      if (d.assigned_user_name) lines.push(t('tags.scan.assignedTo', { name: d.assigned_user_name }))
      if (d.last_done_at) {
        lines.push(
          d.last_done_by
            ? t('tags.scan.lastDoneBy', { date: formatDateShort(d.last_done_at), name: d.last_done_by })
            : t('tags.scan.lastDone', { date: formatDateShort(d.last_done_at) }),
        )
      }
      break
    case 'todo.done':
      if (d.due_date) lines.push(t('tags.scan.dueDate', { date: formatDateShort(d.due_date) }))
      if (d.assigned_user_name) lines.push(t('tags.scan.assignedTo', { name: d.assigned_user_name }))
      break
  }
  return lines
})

const reasonText = computed(() => {
  const key = `tags.scan.reasons.${blockedReason.value}`
  return te(key) ? t(key) : t('tags.scan.reasons.UNKNOWN')
})

/** In den Tag-Haushalt wechseln, wenn der User dort Mitglied ist (Server hat das geprüft). */
function switchToTagHousehold() {
  const id = switchHouseholdTo.value
  if (id && authStore.households.some((h) => h.id === id)) {
    authStore.switchHousehold(id)
  }
}

async function resolve() {
  state.value = 'loading'
  try {
    const r = await store.resolveToken(token.value)
    result.value = r
    const step = nextScanStep(r, authStore.currentHouseholdId)
    if (step.kind === 'navigate') {
      switchHouseholdTo.value = step.switchHouseholdTo
      switchToTagHousehold()
      await router.replace(step.to)
      return
    }
    if (step.kind === 'blocked') {
      blockedReason.value = step.reason
      state.value = 'blocked'
      return
    }
    switchHouseholdTo.value = step.switchHouseholdTo
    slot.value = suggestedSlot(r)
    state.value = 'confirm'
  } catch (err) {
    errorKind.value = scanErrorKind(err)
    state.value = 'error'
  }
}

async function execute() {
  if (!result.value || state.value !== 'confirm') return
  state.value = 'executing'
  try {
    const params = result.value.action === 'pet.feed' ? { slot: slot.value } : undefined
    execResult.value = await store.executeToken(token.value, params)
    state.value = 'done'
  } catch (err) {
    errorKind.value = scanErrorKind(err)
    state.value = 'error'
  }
}

function goToModule() {
  if (!result.value) return
  switchToTagHousehold()
  router.replace(moduleRouteFor(result.value))
}

function goHome() {
  router.replace('/dashboard')
}

onMounted(resolve)
</script>

<template>
  <div class="scan-page">
    <BaseCard padding="lg" class="scan-card">
      <!-- Laden -->
      <div v-if="state === 'loading'" class="scan-center">
        <BaseSpinner />
        <p class="scan-sub">{{ $t('tags.scan.loading') }}</p>
      </div>

      <!-- Bestätigung -->
      <template v-else-if="(state === 'confirm' || state === 'executing') && result">
        <PhQrCode :size="32" class="scan-icon" />
        <p class="scan-label">{{ result.label }}</p>
        <h1 class="scan-title">{{ title }}</h1>
        <p v-if="showHousehold" class="scan-sub">
          {{ $t('tags.scan.household', { name: result.household_name }) }}
        </p>

        <ul v-if="detailLines.length" class="scan-details">
          <li v-for="(line, i) in detailLines" :key="i">{{ line }}</li>
        </ul>

        <div v-if="result.action === 'pet.feed'" class="slot-picker" role="radiogroup" :aria-label="$t('tags.scan.slot')">
          <button
            v-for="s in (['morning', 'evening'] as const)"
            :key="s"
            type="button"
            role="radio"
            :aria-checked="slot === s"
            class="slot-btn"
            :class="{ 'slot-btn--active': slot === s }"
            @click="slot = s"
          >
            {{ s === 'morning' ? $t('tags.scan.slotMorning') : $t('tags.scan.slotEvening') }}
          </button>
        </div>

        <button
          type="button"
          class="big-btn"
          :disabled="state === 'executing'"
          @click="execute"
        >
          <BaseSpinner v-if="state === 'executing'" size="sm" />
          <template v-else>{{ actionText('button') }}</template>
        </button>
        <BaseButton variant="ghost" @click="goHome">{{ $t('tags.scan.cancel') }}</BaseButton>
      </template>

      <!-- Erledigt -->
      <template v-else-if="state === 'done' && result">
        <PhCheckCircle :size="56" weight="fill" class="scan-icon scan-icon--ok" />
        <h1 class="scan-title">
          {{ execResult?.changed === false ? $t('tags.scan.successNoChange') : actionText('done') }}
        </h1>
        <p class="scan-sub">{{ result.target_name ?? result.label }}</p>
        <div class="scan-actions">
          <BaseButton @click="goToModule">{{ $t('tags.scan.openModule') }}</BaseButton>
          <BaseButton variant="secondary" @click="goHome">{{ $t('tags.scan.toDashboard') }}</BaseButton>
        </div>
      </template>

      <!-- Nichts zu tun -->
      <template v-else-if="state === 'blocked' && result">
        <PhCheckCircle :size="48" class="scan-icon" />
        <p class="scan-label">{{ result.label }}</p>
        <h1 class="scan-title">{{ reasonText }}</h1>
        <ul v-if="detailLines.length" class="scan-details">
          <li v-for="(line, i) in detailLines" :key="i">{{ line }}</li>
        </ul>
        <div class="scan-actions">
          <BaseButton @click="goToModule">{{ $t('tags.scan.openModule') }}</BaseButton>
          <BaseButton variant="secondary" @click="goHome">{{ $t('tags.scan.toDashboard') }}</BaseButton>
        </div>
      </template>

      <!-- Fehler -->
      <template v-else>
        <PhWarningCircle :size="48" class="scan-icon scan-icon--warn" />
        <h1 class="scan-title">{{ $t(`tags.scan.errors.${errorKind}`) }}</h1>
        <div class="scan-actions">
          <BaseButton
            v-if="errorKind === 'offline' || errorKind === 'rate_limited' || errorKind === 'unknown'"
            @click="resolve"
          >
            {{ $t('tags.scan.retry') }}
          </BaseButton>
          <BaseButton variant="secondary" @click="goHome">{{ $t('tags.scan.toDashboard') }}</BaseButton>
        </div>
      </template>
    </BaseCard>
  </div>
</template>

<style scoped>
.scan-page {
  min-height: 70vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
}

.scan-card {
  width: 100%;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  text-align: center;
}

.scan-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-6) 0;
}

.scan-icon {
  color: var(--acc);
}

.scan-icon--ok {
  color: var(--ok);
}

.scan-icon--warn {
  color: var(--color-warning-strong);
}

.scan-label {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
}

.scan-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-title-page);
  color: var(--ink);
  line-height: var(--line-height-snug);
}

.scan-sub {
  margin: 0;
  color: var(--sub);
  font-size: var(--text-sm);
}

.scan-details {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--sub);
}

.slot-picker {
  display: flex;
  gap: var(--space-2);
}

.slot-btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  border: 1px solid var(--line-strong);
  background: var(--card);
  color: var(--ink);
  font: inherit;
  cursor: pointer;
}

.slot-btn--active {
  background: var(--ink);
  color: var(--card);
  border-color: var(--ink);
}

.big-btn {
  width: 100%;
  min-height: 72px;
  border: none;
  border-radius: var(--radius-card);
  background: var(--acc);
  color: var(--color-on-accent);
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform var(--transition-fast), opacity var(--transition-fast);
}

.big-btn:active {
  transform: scale(0.98);
}

.big-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.scan-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: center;
}
</style>
