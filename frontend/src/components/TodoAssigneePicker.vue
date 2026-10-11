<script setup lang="ts">
/**
 * Auswahl der zuständigen Personen einer Aufgabe (Mehrfachauswahl).
 *
 * Chips zum An-/Abwählen (aria-pressed), dazu "Alle" und "Niemand". Keine Auswahl
 * heisst "offen für alle". Bereits eingetragene Ex-Mitglieder erscheinen nicht als
 * Chip, bleiben aber in der Auswahl, bis "Alle"/"Niemand" sie ersetzt.
 */
import { computed } from 'vue'
import { PhCheck } from '@phosphor-icons/vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import type { HouseholdMemberInfo } from '../types'
import { toggleAssignee } from '../utils/todoAssignees'

const props = defineProps<{
  modelValue: string[]
  members: HouseholdMemberInfo[]
}>()

const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()

const selected = computed(() => new Set(props.modelValue))
const allSelected = computed(
  () => props.members.length > 0 && props.members.every(m => selected.value.has(m.id)),
)
// "Niemand" ist aktiv, wenn kein aktuelles Mitglied gewählt ist
const noneSelected = computed(() => !props.members.some(m => selected.value.has(m.id)))

function firstName(member: HouseholdMemberInfo): string {
  return member.display_name.split(' ')[0]
}

function toggle(id: string) {
  emit('update:modelValue', toggleAssignee(props.modelValue, id))
}

function selectAll() {
  emit('update:modelValue', props.members.map(m => m.id))
}

function selectNone() {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="assignee-picker" role="group" :aria-label="$t('todos.assignees')">
    <div class="assignee-picker__head">
      <span class="assignee-picker__label" aria-hidden="true">{{ $t('todos.assignees') }}</span>
      <div class="assignee-picker__quick">
        <button
          type="button"
          class="assignee-picker__quick-btn tap-target"
          :aria-pressed="allSelected"
          @click="selectAll"
        >
          {{ $t('todos.assignAll') }}
        </button>
        <button
          type="button"
          class="assignee-picker__quick-btn tap-target"
          :aria-pressed="noneSelected"
          @click="selectNone"
        >
          {{ $t('todos.assignNone') }}
        </button>
      </div>
    </div>
    <div class="assignee-picker__chips">
      <button
        v-for="member in members"
        :key="member.id"
        type="button"
        class="assignee-chip"
        :class="{ 'assignee-chip--selected': selected.has(member.id) }"
        :aria-pressed="selected.has(member.id)"
        :title="member.display_name"
        @click="toggle(member.id)"
      >
        <BaseAvatar :name="member.display_name" :user-id="member.id" size="sm" />
        <span class="assignee-chip__name">{{ firstName(member) }}</span>
        <PhCheck v-if="selected.has(member.id)" :size="14" weight="bold" aria-hidden="true" />
      </button>
    </div>
    <p v-if="noneSelected" class="assignee-picker__hint">{{ $t('todos.openForAll') }}</p>
  </div>
</template>

<style scoped>
.assignee-picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.assignee-picker__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.assignee-picker__label {
  font-size: var(--text-sm);
  color: var(--sub);
  font-weight: var(--font-weight-medium);
}

.assignee-picker__quick {
  display: flex;
  /* Abstand, damit sich die 44-px-Tap-Flächen nicht überlappen */
  gap: var(--space-3);
}

.assignee-picker__quick-btn {
  background: none;
  border: none;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-size: var(--text-sm);
  color: var(--acc);
  cursor: pointer;
}

.assignee-picker__quick-btn[aria-pressed='true'] {
  color: var(--ink);
  font-weight: var(--font-weight-semibold);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.assignee-picker__quick-btn:focus-visible,
.assignee-chip:focus-visible {
  outline: var(--focus-outline);
  outline-offset: 2px;
}

.assignee-picker__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.assignee-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  min-height: var(--touch-target);
  max-width: 100%;
  padding: 0 var(--space-3) 0 var(--space-2);
  border-radius: var(--radius-full);
  border: 1px solid transparent;
  background: var(--chip);
  color: var(--ink);
  font-family: var(--font-family);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.assignee-chip--selected {
  background: var(--acc-soft);
  border-color: var(--acc);
}

.assignee-chip__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assignee-picker__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--sub);
}
</style>
