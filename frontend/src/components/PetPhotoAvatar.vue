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

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'sm': return 'w-10 h-10'
    case 'lg': return 'w-24 h-24'
    default: return 'w-12 h-12'
  }
})

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
    :class="[sizeClasses, 'rounded-full overflow-hidden bg-surface-variant flex items-center justify-center shrink-0']"
  >
    <div v-if="loading" class="animate-pulse w-full h-full bg-surface-variant" />
    <img
      v-else-if="objectUrl"
      :src="objectUrl"
      :alt="petName ?? ''"
      class="w-full h-full object-cover"
    />
    <PhCat v-else :size="iconSize" class="text-on-surface-variant" />
  </div>
</template>
