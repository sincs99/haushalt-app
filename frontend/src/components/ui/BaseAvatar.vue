<script setup lang="ts">
import { computed } from 'vue'
import { getMemberColor } from '../../utils/memberColor'

const props = withDefaults(defineProps<{
  name: string
  userId: string
  size?: 'sm' | 'md'
}>(), {
  size: 'sm',
})

// Initialen: Bei 2 Wörtern → Anfangsbuchstaben beider; sonst erste 2 Zeichen
const initials = computed(() => {
  const parts = props.name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return props.name.trim().substring(0, 2).toUpperCase()
})

const sizeClass = computed(() => `base-avatar--${props.size}`)
</script>

<template>
  <span
    class="base-avatar"
    :class="sizeClass"
    :style="{
      backgroundColor: getMemberColor(props.userId),
      color: '#fff',
    }"
    aria-hidden="true"
    :title="name"
  >
    {{ initials }}
  </span>
</template>

<style scoped>
.base-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-semibold);
  flex-shrink: 0;
  line-height: 1;
  user-select: none;
}

.base-avatar--sm {
  width: 22px;
  height: 22px;
  font-size: 10px;
}

.base-avatar--md {
  width: 32px;
  height: 32px;
  font-size: 13px;
}
</style>
