<script setup lang="ts">
import { computed, toRef } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useProtectedImage } from '../composables/useProtectedImage'
import { PhCat } from '@phosphor-icons/vue'

const props = defineProps<{
  photoFileId: string | null | undefined
  petName?: string
  size?: 'sm' | 'md' | 'lg'
}>()

const authStore = useAuthStore()

const householdId = computed(() => authStore.currentHouseholdId)
const fileId = toRef(() => props.photoFileId)

const { objectUrl, loading } = useProtectedImage(householdId, fileId)

const iconSize = computed(() => {
  switch (props.size) {
    case 'sm': return 20
    case 'lg': return 48
    default: return 24
  }
})
</script>

<template>
  <div
    class="pet-avatar"
    :class="'pet-avatar--' + (size ?? 'md')"
  >
    <div v-if="loading" class="pet-avatar__loading" />
    <img
      v-else-if="objectUrl"
      :src="objectUrl"
      :alt="petName ?? ''"
      class="pet-avatar__img"
    />
    <PhCat v-else :size="iconSize" class="pet-avatar__icon" />
  </div>
</template>

<style scoped>
.pet-avatar {
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--chip);
}

.pet-avatar--sm {
  width: 40px;
  height: 40px;
}

.pet-avatar--md {
  width: 48px;
  height: 48px;
}

.pet-avatar--lg {
  width: 96px;
  height: 96px;
}

.pet-avatar__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pet-avatar__loading {
  width: 100%;
  height: 100%;
  background: var(--chip);
  animation: pet-avatar-pulse 1.5s ease-in-out infinite;
}

.pet-avatar__icon {
  color: var(--sub);
}

@keyframes pet-avatar-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
