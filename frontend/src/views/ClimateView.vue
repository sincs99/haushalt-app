<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhBatteryWarning, PhDrop, PhThermometerSimple, PhTrash, PhWifiSlash } from '@phosphor-icons/vue'
import { useSensorsStore } from '../stores/sensors'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { groupByRoom, humidityLevel, isBatteryLow, isOffline, type ChartPoint } from '../utils/climate'
import type { SensorDevice, SensorReadingPoint } from '../types'

import PageHeader from '../components/ui/PageHeader.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BasePillTabs from '../components/ui/BasePillTabs.vue'
import SensorChart from '../components/SensorChart.vue'

const { t, locale } = useI18n()
const { run, isPending } = useAsyncAction()
const socket = useSocket()
const store = useSensorsStore()
const authStore = useAuthStore()
const { loadError, reloading, reload } = useLoader(() => store.fetchDevices())

const isAdmin = computed(() => authStore.currentHousehold?.role === 'admin')
// Nach Raum, dann Name sortiert; der Raum steht auf der Karte
const sortedDevices = computed(() => groupByRoom(store.devices, locale.value).flatMap((group) => group.devices))
const hasDevices = computed(() => store.devices.length > 0)

// "Offline" und "vor x Minuten" hängen von der Uhr ab, nicht nur von neuen Daten
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | undefined

const valueFormat = computed(() => new Intl.NumberFormat(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }))
const percentFormat = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }))
const relativeFormat = computed(() => new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }))

function lastSeenLabel(device: SensorDevice): string {
  if (!device.last_seen_at) return t('climate.neverSeen')
  const minutes = Math.round((new Date(device.last_seen_at).getTime() - now.value) / 60_000)
  if (minutes >= 0) return t('climate.justNow')
  if (minutes > -60) return relativeFormat.value.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (hours > -48) return relativeFormat.value.format(hours, 'hour')
  return relativeFormat.value.format(Math.round(hours / 24), 'day')
}

// ── Detail-Dialog: Verlauf und Einstellungen eines Sensors ──
const selectedId = ref<string | null>(null)
// Aus dem Store lesen, damit neue Messwerte auch im offenen Dialog erscheinen
const selected = computed(() => store.devices.find((d) => d.id === selectedId.value) ?? null)

const RANGES = { day: 24, week: 168 } as const
type RangeKey = keyof typeof RANGES
const range = ref<RangeKey>('day')
const rangeTabs = computed(() => [
  { key: 'day', label: t('climate.rangeDay') },
  { key: 'week', label: t('climate.rangeWeek') },
])

const readings = ref<SensorReadingPoint[]>([])
const readingsLoading = ref(false)
const readingsError = ref(false)
const windowEnd = ref(Date.now())

const windowStart = computed(() => windowEnd.value - RANGES[range.value] * 60 * 60 * 1000)
// Tagesansicht: Einzelwerte alle paar Minuten; Wochenansicht: Stundenmittel
const maxGapMs = computed(() => (range.value === 'day' ? 45 : 150) * 60 * 1000)

function series(key: 'temperature' | 'humidity'): ChartPoint[] {
  return readings.value
    .filter((r) => r[key] !== null)
    .map((r) => ({ time: new Date(r.recorded_at).getTime(), value: r[key] as number }))
}
const temperatureSeries = computed(() => series('temperature'))
const humiditySeries = computed(() => series('humidity'))

async function loadReadings() {
  const id = selectedId.value
  if (!id) return
  const requestedRange = range.value
  readingsLoading.value = true
  readingsError.value = false
  try {
    const result = await store.fetchReadings(id, RANGES[requestedRange])
    if (result === null || selectedId.value !== id || range.value !== requestedRange) return
    readings.value = result
    windowEnd.value = Date.now()
  } catch {
    if (selectedId.value === id && range.value === requestedRange) readingsError.value = true
  } finally {
    if (selectedId.value === id && range.value === requestedRange) readingsLoading.value = false
  }
}

const editName = ref('')
const editRoom = ref('')
const confirmDelete = ref(false)

const editDirty = computed(() => {
  const device = selected.value
  return !!device && (editName.value.trim() !== device.name || (editRoom.value.trim() || null) !== device.room)
})

function openDevice(device: SensorDevice) {
  selectedId.value = device.id
  editName.value = device.name
  editRoom.value = device.room ?? ''
  range.value = 'day'
  readings.value = []
  void loadReadings()
}

function closeDevice() {
  confirmDelete.value = false
  selectedId.value = null
  readings.value = []
}

watch(range, () => {
  readings.value = []
  void loadReadings()
})

// Sensor von jemand anderem gelöscht: Dialog schliessen
watch(selected, (device) => {
  if (selectedId.value && !device) closeDevice()
})

async function saveDevice() {
  const device = selected.value
  const name = editName.value.trim()
  if (!device || !name) return
  await run(
    () => store.updateDevice(device.id, { name, room: editRoom.value.trim() || null }),
    { key: 'save', success: t('climate.saved'), error: t('climate.saveError') },
  )
}

async function deleteDevice() {
  const device = selected.value
  if (!device) return
  closeDevice()
  await run(() => store.deleteDevice(device.id), {
    key: `delete:${device.id}`,
    success: t('climate.deleted'),
    error: t('climate.deleteError'),
  })
}

// ── Echtzeit ──
function handleReconnect() {
  reload()
}

// Haushaltswechsel: Daten des neuen Haushalts laden (der Store wurde geleert)
watch(() => authStore.currentHouseholdId, (id) => {
  closeDevice()
  if (id) reload()
})

onMounted(() => {
  reload()
  clock = setInterval(() => { now.value = Date.now() }, 60_000)
  socket.on('sensor_updated', store.handleSensorUpdated)
  socket.on('sensor_deleted', store.handleSensorDeleted)
  socket.onReconnect(handleReconnect)
})

onUnmounted(() => {
  clearInterval(clock)
  socket.off('sensor_updated', store.handleSensorUpdated)
  socket.off('sensor_deleted', store.handleSensorDeleted)
  socket.offReconnect(handleReconnect)
})
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('climate.title')" />

    <template v-if="(store.loading || reloading) && !hasDevices && !loadError">
      <div class="climate-grid">
        <BaseSkeleton v-for="i in 4" :key="i" width="100%" height="120px" />
      </div>
    </template>

    <BaseErrorState v-else-if="loadError && !hasDevices" :retrying="reloading" @retry="reload" />

    <BaseEmptyState
      v-else-if="!hasDevices"
      :icon="PhThermometerSimple"
      :title="$t('climate.emptyTitle')"
      :subtitle="isAdmin ? $t('climate.emptySubtitleAdmin') : $t('climate.emptySubtitle')"
    >
      <template v-if="isAdmin" #action>
        <BaseButton variant="secondary" size="sm" @click="$router.push('/household')">
          {{ $t('climate.emptyAction') }}
        </BaseButton>
      </template>
    </BaseEmptyState>

    <template v-else>
      <div class="climate-grid">
      <button
        v-for="device in sortedDevices"
        :key="device.id"
        type="button"
        class="sensor-card"
        :class="{ 'sensor-card--offline': isOffline(device.last_seen_at, now) }"
        @click="openDevice(device)"
      >
        <span class="sensor-card__name">{{ device.name }}</span>
        <span v-if="device.room" class="sensor-card__room">{{ device.room }}</span>

        <span class="sensor-card__temperature">
          <template v-if="device.temperature !== null">
            {{ valueFormat.format(device.temperature) }}<span class="sensor-card__unit">°C</span>
          </template>
          <template v-else>–</template>
        </span>

        <span v-if="device.humidity !== null" class="sensor-card__humidity">
          <PhDrop :size="16" aria-hidden="true" />
          {{ percentFormat.format(device.humidity) }} %
          <span
            v-if="humidityLevel(device.humidity) !== 'ok'"
            class="sensor-badge sensor-badge--warning"
          >
            {{ $t(`climate.humidity.${humidityLevel(device.humidity)}`) }}
          </span>
        </span>

        <span class="sensor-card__meta">
          <span v-if="isOffline(device.last_seen_at, now)" class="sensor-badge sensor-badge--muted">
            <PhWifiSlash :size="12" aria-hidden="true" />
            {{ $t('climate.offline') }}
          </span>
          <span v-if="isBatteryLow(device.battery)" class="sensor-badge sensor-badge--warning">
            <PhBatteryWarning :size="12" aria-hidden="true" />
            {{ $t('climate.batteryLow') }}
          </span>
          <span class="sensor-card__seen">{{ lastSeenLabel(device) }}</span>
        </span>
      </button>
      </div>
    </template>

    <!-- Detail: Verlauf und Einstellungen -->
    <BaseDialog :open="!!selected" :title="selected?.name" @close="closeDevice">
      <template v-if="selected">
        <dl class="detail-stats">
          <div>
            <dt>{{ $t('climate.temperature') }}</dt>
            <dd>{{ selected.temperature !== null ? `${valueFormat.format(selected.temperature)} °C` : '–' }}</dd>
          </div>
          <div>
            <dt>{{ $t('climate.humidityLabel') }}</dt>
            <dd>{{ selected.humidity !== null ? `${percentFormat.format(selected.humidity)} %` : '–' }}</dd>
          </div>
          <div>
            <dt>{{ $t('climate.battery') }}</dt>
            <dd>{{ selected.battery !== null ? `${percentFormat.format(selected.battery)} %` : '–' }}</dd>
          </div>
        </dl>
        <p class="detail-seen">{{ $t('climate.lastSeen', { time: lastSeenLabel(selected) }) }}</p>

        <BasePillTabs v-model="range" :tabs="rangeTabs" />

        <BaseErrorState v-if="readingsError" :retrying="readingsLoading" @retry="loadReadings" />
        <div v-else class="detail-charts" :class="{ 'detail-charts--loading': readingsLoading }">
          <SensorChart
            :title="$t('climate.temperature')"
            unit="°C"
            :points="temperatureSeries"
            :from="windowStart"
            :to="windowEnd"
            :max-gap-ms="maxGapMs"
            color="var(--acc)"
          />
          <SensorChart
            :title="$t('climate.humidityLabel')"
            unit="%"
            :points="humiditySeries"
            :from="windowStart"
            :to="windowEnd"
            :max-gap-ms="maxGapMs"
            :min-span="10"
            color="var(--p1)"
          />
        </div>

        <form id="sensor-edit-form" class="detail-form" @submit.prevent="saveDevice">
          <BaseInput v-model="editName" :label="$t('climate.nameLabel')" maxlength="80" autocomplete="off" />
          <BaseInput
            v-model="editRoom"
            :label="$t('climate.roomLabel')"
            :placeholder="$t('climate.roomPlaceholder')"
            maxlength="60"
            autocomplete="off"
          />
        </form>
      </template>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="danger" @click="confirmDelete = true">
            <PhTrash :size="16" />
            {{ $t('common.delete') }}
          </BaseButton>
          <div class="dialog-actions__spacer" />
          <BaseButton
            type="submit"
            form="sensor-edit-form"
            :disabled="!editDirty || !editName.trim()"
            :loading="isPending('save')"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <BaseDialog :open="confirmDelete" :title="$t('climate.deleteTitle')" danger @close="confirmDelete = false">
      <p class="confirm-text">{{ $t('climate.deleteText') }}</p>
      <template #footer>
        <BaseButton variant="secondary" @click="confirmDelete = false">{{ $t('common.cancel') }}</BaseButton>
        <BaseButton variant="danger" @click="deleteDevice">{{ $t('common.delete') }}</BaseButton>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.climate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.sensor-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-3) var(--space-4);
  border: none;
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.sensor-card:hover {
  background: var(--chip);
}

.sensor-card:focus-visible {
  outline: var(--focus-outline);
  outline-offset: 2px;
}

.sensor-card__name {
  max-width: 100%;
  overflow: hidden;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sensor-card__room {
  max-width: 100%;
  overflow: hidden;
  font-size: var(--text-xs);
  color: var(--sub);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sensor-card__temperature {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--font-weight-semibold);
  font-variant-numeric: tabular-nums;
  line-height: var(--line-height-tight);
}

.sensor-card__unit {
  margin-left: var(--space-0-5);
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
  color: var(--sub);
}

/* Offline: Die Werte sind alt – zurücknehmen, aber lesbar lassen */
.sensor-card--offline .sensor-card__temperature,
.sensor-card--offline .sensor-card__humidity {
  color: var(--sub);
}

.sensor-card__humidity {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.sensor-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-1);
}

.sensor-card__seen {
  font-size: var(--text-xs);
  color: var(--sub);
}

.sensor-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--badge-padding);
  border-radius: var(--radius-full);
  font-size: var(--text-badge);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.sensor-badge--warning {
  background: var(--color-warning-soft);
  color: var(--color-warning-strong);
}

.sensor-badge--muted {
  background: var(--chip);
  color: var(--sub);
}

.detail-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
  margin: 0;
}

.detail-stats dt {
  font-size: var(--text-xs);
  color: var(--sub);
}

.detail-stats dd {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.detail-seen {
  margin: var(--space-1) 0 var(--space-4);
  font-size: var(--text-xs);
  color: var(--sub);
}

.detail-charts {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  margin: var(--space-4) 0 var(--space-5);
  transition: opacity var(--transition-fast);
}

.detail-charts--loading {
  opacity: 0.5;
}

.detail-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--line);
}

.dialog-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.dialog-actions__spacer {
  flex: 1;
}

.confirm-text {
  margin: 0;
  color: var(--ink);
}
</style>
