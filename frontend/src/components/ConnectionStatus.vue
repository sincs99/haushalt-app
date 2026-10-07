<script setup lang="ts">
import { computed } from 'vue'
import { useSocket } from '../composables/useSocket'
import { useConnectivity } from '../composables/useConnectivity'

const { isConnected } = useSocket()
const { isOnline } = useConnectivity()
const status = computed(() => !isOnline.value ? 'offline' : isConnected.value ? 'connected' : 'reconnecting')
</script>

<template>
  <div class="connection-status">
    <p class="connection-status__label" role="status">
      <span class="sync-dot" :class="`sync-dot--${status}`" aria-hidden="true" />
      {{ $t(`sync.${status}`) }}
    </p>
    <p class="connection-status__hint">{{ $t(`sync.${status}Hint`) }}</p>
  </div>
</template>

<style scoped>
.connection-status__label { display: flex; align-items: center; gap: var(--space-2); margin: 0 0 var(--space-1); font-size: var(--text-sm); }
.sync-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.sync-dot--connected { background: var(--ok); }
.sync-dot--reconnecting { background: var(--color-warning); }
.sync-dot--offline { background: var(--color-danger); }
.connection-status__hint { color: var(--sub); font-size: var(--text-xs); line-height: 1.5; margin: 0; }
</style>
