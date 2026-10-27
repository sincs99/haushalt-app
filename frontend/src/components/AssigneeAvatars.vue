<script setup lang="ts">
import { computed } from 'vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import { namedStack } from '../utils/todoAssignees'
import type { DashboardAssignee } from '../types'

// Zuständige als überlappende Avatare: max. 3, danach "+n"
const props = defineProps<{
  assignees: DashboardAssignee[]
}>()

const stack = computed(() => namedStack(props.assignees))
</script>

<template>
  <span
    v-if="stack.shown.length"
    class="avatar-stack"
    role="img"
    :aria-label="$t('todos.assigneesAria', { names: stack.label })"
    :title="stack.label"
  >
    <BaseAvatar
      v-for="person in stack.shown"
      :key="person.user_id"
      :name="person.display_name"
      :user-id="person.user_id"
      size="sm"
    />
    <span v-if="stack.overflow" class="avatar-stack__more" aria-hidden="true">
      +{{ stack.overflow }}
    </span>
  </span>
</template>

<style scoped>
.avatar-stack {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

/* Wurzel-Element von BaseAvatar trägt auch die Scope-ID dieser Komponente */
.avatar-stack > .base-avatar {
  box-shadow: 0 0 0 2px var(--bg);
}

.avatar-stack > .base-avatar + .base-avatar {
  margin-left: calc(-1 * var(--space-1-5));
}

.avatar-stack__more {
  margin-left: var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
}
</style>
