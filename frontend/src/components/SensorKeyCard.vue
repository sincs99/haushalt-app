<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhCopy, PhThermometerSimple } from '@phosphor-icons/vue'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseDialog from './ui/BaseDialog.vue'
import { API_BASE } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import { createOnlineSensorKeyRepository } from '../repositories/sensorsRepository'
import { useWidgetToken } from '../composables/useWidgetToken'
import { translateApiError } from '../utils/apiErrors'
import { formatDate } from '../utils/dates'

/**
 * Raumklima: Schreib-Schlüssel des Haushalts, mit dem eine Brücke (z. B. Zigbee2MQTT)
 * Messwerte liefert. Erzeugen und widerrufen dürfen nur Admins. Doku: docs/sensors.md
 */
const { t } = useI18n()
const { showToast } = useToast()
const authStore = useAuthStore()
const repo = createOnlineSensorKeyRepository()

const confirmRevoke = ref(false)
const confirmReplace = ref(false)

const householdId = computed(() => authStore.currentHouseholdId)
const isAdmin = computed(() => authStore.currentHousehold?.role === 'admin')

function buildExample(token: string): string {
  const base = API_BASE || window.location.origin
  return [
    `curl -X POST ${base}/api/sensors/ingest \\`,
    `  -H "Authorization: Bearer ${token}" \\`,
    '  -H "Content-Type: application/json" \\',
    '  -d \'{"readings":[{"device_id":"wohnzimmer","name":"Wohnzimmer","temperature":21.4,"humidity":48,"battery":87}]}\'',
  ].join('\n')
}

// Zustand an den aktuellen Haushalt gebunden, gleiche Mechanik wie beim Widget-Schlüssel (CASA-50)
const { status, script: example, busy, load, create: createKey, revoke: revokeKey } = useWidgetToken(
  householdId,
  repo,
  buildExample,
  (error) => showToast(translateApiError(error), 'error'),
)

onMounted(load)

async function create() {
  confirmReplace.value = false
  await createKey()
}

async function revoke() {
  confirmRevoke.value = false
  if (await revokeKey()) showToast(t('sensorKey.revoked'), 'success')
}

async function copyExample() {
  if (!example.value) return
  try {
    await navigator.clipboard.writeText(example.value)
    showToast(t('sensorKey.copied'), 'success')
  } catch {
    showToast(t('sensorKey.copyFailed'), 'error')
  }
}
</script>

<template>
  <BaseCard>
    <template #header>
      <span class="sensor-key__title">
        <PhThermometerSimple :size="20" />
        {{ t('sensorKey.title') }}
      </span>
    </template>

    <p class="sensor-key__hint">{{ t('sensorKey.hint') }}</p>

    <!-- Direkt nach dem Erzeugen: Beispielaufruf mit Schlüssel (nur jetzt sichtbar) -->
    <div v-if="example" class="sensor-key__example">
      <p class="sensor-key__warning">{{ t('sensorKey.onlyNow') }}</p>
      <textarea
        class="sensor-key__code"
        :value="example"
        readonly
        rows="5"
        :aria-label="t('sensorKey.exampleLabel')"
        @focus="($event.target as HTMLTextAreaElement).select()"
      />
      <div class="sensor-key__actions">
        <BaseButton size="sm" @click="copyExample">
          <PhCopy :size="16" />
          {{ t('sensorKey.copy') }}
        </BaseButton>
      </div>
    </div>

    <template v-else-if="status?.exists">
      <p class="sensor-key__state">{{ t('sensorKey.active', { prefix: status.token_prefix }) }}</p>
      <p class="sensor-key__meta">
        {{ t('sensorKey.createdAt', { date: formatDate(status.created_at!) }) }}
        ·
        {{ status.last_used_at
          ? t('sensorKey.lastUsed', { date: formatDate(status.last_used_at) })
          : t('sensorKey.neverUsed') }}
      </p>
    </template>

    <div v-if="isAdmin" class="sensor-key__actions">
      <BaseButton v-if="!status?.exists" size="sm" :loading="busy" @click="create">
        {{ t('sensorKey.create') }}
      </BaseButton>
      <template v-else>
        <BaseButton variant="secondary" size="sm" :disabled="busy" @click="confirmReplace = true">
          {{ t('sensorKey.replace') }}
        </BaseButton>
        <BaseButton variant="ghost" size="sm" :disabled="busy" @click="confirmRevoke = true">
          {{ t('sensorKey.revoke') }}
        </BaseButton>
      </template>
    </div>
    <p v-else class="sensor-key__meta">{{ t('sensorKey.adminOnly') }}</p>

    <BaseDialog :open="confirmReplace" :title="t('sensorKey.replace')" @close="confirmReplace = false">
      <p class="sensor-key__dialog-text">{{ t('sensorKey.replaceConfirm') }}</p>
      <template #footer>
        <BaseButton variant="secondary" @click="confirmReplace = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton :loading="busy" @click="create">{{ t('sensorKey.replace') }}</BaseButton>
      </template>
    </BaseDialog>

    <BaseDialog :open="confirmRevoke" :title="t('sensorKey.revoke')" danger @close="confirmRevoke = false">
      <p class="sensor-key__dialog-text">{{ t('sensorKey.revokeConfirm') }}</p>
      <template #footer>
        <BaseButton variant="secondary" @click="confirmRevoke = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton variant="danger" :loading="busy" @click="revoke">{{ t('sensorKey.revoke') }}</BaseButton>
      </template>
    </BaseDialog>
  </BaseCard>
</template>

<style scoped>
.sensor-key__title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.sensor-key__hint,
.sensor-key__meta {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--sub);
}

.sensor-key__dialog-text {
  margin: 0;
  color: var(--ink);
}

.sensor-key__state {
  margin: 0 0 var(--space-1);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.sensor-key__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sensor-key__example {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-btn);
  background: var(--chip);
}

.sensor-key__warning {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-warning-strong);
}

.sensor-key__code {
  width: 100%;
  padding: var(--space-2);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  background: var(--card);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  resize: vertical;
}
</style>
