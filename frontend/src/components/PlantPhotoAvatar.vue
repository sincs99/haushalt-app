<script setup lang="ts">
import { computed, toRef } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useProtectedImage } from '../composables/useProtectedImage'
import { PhPlant } from '@phosphor-icons/vue'

const props = defineProps<{
  photoFileId: string | null | undefined
  plantName?: string
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
    class="plant-avatar"
    :class="'plant-avatar--' + (size ?? 'md')"
  >
    <div v-if="loading" class="plant-avatar__loading" />
    <img
      v-else-if="objectUrl"
      :src="objectUrl"
      :alt="plantName ?? ''"
      class="plant-avatar__img"
    />
    <PhPlant v-else :size="iconSize" class="plant-avatar__icon" />
  </div>
</template>

<style scoped>
.plant-avatar {
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--chip);
}

.plant-avatar--sm {
  width: 40px;
  height: 40px;
}

.plant-avatar--md {
  width: 48px;
  height: 48px;
}

.plant-avatar--lg {
  width: 96px;
  height: 96px;
}

.plant-avatar__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.plant-avatar__loading {
  width: 100%;
  height: 100%;
  background: var(--chip);
  animation: plant-avatar-pulse 1.5s ease-in-out infinite;
}

.plant-avatar__icon {
  color: var(--sub);
}

@keyframes plant-avatar-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
