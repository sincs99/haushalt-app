<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { chartPath, chartPosition, chartScale, nearestPoint, type ChartPoint } from '../utils/climate'

/**
 * Verlauf einer Messgrösse als Linie über ein festes Zeitfenster.
 *
 * Die Linie liegt in einem gestreckten SVG (0–100 in beiden Achsen); Beschriftung,
 * Markierung und Tooltip sind HTML, damit Schrift und Punkt nicht mitverzerrt werden.
 * Pro Diagramm eine Grösse und eine Achse – Temperatur und Feuchte stehen untereinander.
 */
const props = defineProps<{
  title: string
  unit: string
  points: ChartPoint[]
  /** Zeitfenster in Millisekunden (Epoch) */
  from: number
  to: number
  /** Grösserer Abstand zwischen zwei Punkten wird als Lücke gezeichnet */
  maxGapMs: number
  /** CSS-Farbe der Linie */
  color: string
  /** Kleinste Achsenspanne, damit Rauschen flach bleibt */
  minSpan?: number
}>()

const { locale, t } = useI18n()

const scale = computed(() => chartScale(props.points, props.minSpan ?? 2))
const path = computed(() => chartPath(props.points, props.from, props.to, scale.value, props.maxGapMs))
const ticks = computed(() => {
  const { low, high } = scale.value
  return [high, (low + high) / 2, low]
})

const numberFormat = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }))
const multiDay = computed(() => props.to - props.from > 36 * 60 * 60 * 1000)
const timeFormat = computed(() => new Intl.DateTimeFormat(locale.value, multiDay.value
  ? { weekday: 'short', hour: '2-digit', minute: '2-digit' }
  : { hour: '2-digit', minute: '2-digit' }))
const axisFormat = computed(() => new Intl.DateTimeFormat(locale.value, multiDay.value
  ? { weekday: 'short', day: 'numeric' }
  : { hour: '2-digit', minute: '2-digit' }))

const xLabels = computed(() => {
  const steps = 4
  return Array.from({ length: steps + 1 }, (_, i) =>
    axisFormat.value.format(new Date(props.from + ((props.to - props.from) * i) / steps)))
})

const summary = computed(() => {
  if (props.points.length === 0) return t('climate.chartEmpty')
  const values = props.points.map((p) => p.value)
  return t('climate.chartSummary', {
    title: props.title,
    min: numberFormat.value.format(Math.min(...values)),
    max: numberFormat.value.format(Math.max(...values)),
    unit: props.unit,
  })
})

// ── Hover/Touch: nächster Messpunkt mit Fadenkreuz und Tooltip ──
const plotRef = ref<HTMLElement | null>(null)
const hovered = ref<ChartPoint | null>(null)
const hoveredPosition = computed(() =>
  hovered.value ? chartPosition(hovered.value, props.from, props.to, scale.value) : null)

function onPointer(event: PointerEvent) {
  const rect = plotRef.value?.getBoundingClientRect()
  if (!rect || rect.width === 0) return
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
  hovered.value = nearestPoint(props.points, props.from + ratio * (props.to - props.from))
}

function clearHover() {
  hovered.value = null
}
</script>

<template>
  <figure class="sensor-chart">
    <figcaption class="sensor-chart__title">{{ title }} <span class="sensor-chart__unit">({{ unit }})</span></figcaption>

    <div class="sensor-chart__body">
      <div class="sensor-chart__y" aria-hidden="true">
        <span v-for="tick in ticks" :key="tick">{{ numberFormat.format(tick) }}</span>
      </div>

      <div
        ref="plotRef"
        class="sensor-chart__plot"
        role="img"
        :aria-label="summary"
        @pointermove="onPointer"
        @pointerdown="onPointer"
        @pointerleave="clearHover"
        @pointercancel="clearHover"
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <line v-for="y in [0, 50, 100]" :key="y" class="sensor-chart__grid" x1="0" x2="100" :y1="y" :y2="y" />
          <path v-if="path" class="sensor-chart__line" :d="path" :style="{ stroke: color }" />
        </svg>

        <p v-if="points.length === 0" class="sensor-chart__empty">{{ t('climate.chartEmpty') }}</p>

        <template v-if="hovered && hoveredPosition">
          <span class="sensor-chart__cross" :style="{ left: `${hoveredPosition.x}%` }" />
          <span
            class="sensor-chart__dot"
            :style="{ left: `${hoveredPosition.x}%`, top: `${hoveredPosition.y}%`, background: color }"
          />
          <span
            class="sensor-chart__tip"
            :class="{ 'sensor-chart__tip--left': hoveredPosition.x > 60 }"
            :style="{ left: `${hoveredPosition.x}%` }"
          >
            <strong>{{ numberFormat.format(hovered.value) }} {{ unit }}</strong>
            {{ timeFormat.format(new Date(hovered.time)) }}
          </span>
        </template>
      </div>
    </div>

    <div class="sensor-chart__x" aria-hidden="true">
      <span v-for="(label, i) in xLabels" :key="i">{{ label }}</span>
    </div>
  </figure>
</template>

<style scoped>
.sensor-chart {
  margin: 0;
}

.sensor-chart__title {
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.sensor-chart__unit {
  font-weight: var(--font-weight-normal);
  color: var(--sub);
}

.sensor-chart__body {
  display: flex;
  gap: var(--space-2);
  height: 120px;
}

.sensor-chart__y {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 2.25em;
  /* Beschriftung mittig auf der Gitterlinie */
  margin: -0.6em 0;
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--sub);
}

.sensor-chart__plot {
  position: relative;
  flex: 1;
  min-width: 0;
  touch-action: pan-y;
  cursor: crosshair;
}

.sensor-chart__plot svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.sensor-chart__grid {
  stroke: var(--line);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.sensor-chart__line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
}

.sensor-chart__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
}

.sensor-chart__cross {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--line-strong);
  pointer-events: none;
}

.sensor-chart__dot {
  position: absolute;
  width: 10px;
  height: 10px;
  margin: -5px 0 0 -5px;
  border: 2px solid var(--card);
  border-radius: var(--radius-full);
  pointer-events: none;
}

.sensor-chart__tip {
  position: absolute;
  top: 0;
  display: flex;
  flex-direction: column;
  margin-left: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-md);
  background: var(--ink);
  color: var(--card);
  font-size: var(--text-xs);
  line-height: var(--line-height-snug);
  white-space: nowrap;
  pointer-events: none;
  z-index: var(--z-raised);
}

.sensor-chart__tip--left {
  margin-left: 0;
  transform: translateX(calc(-100% - var(--space-2)));
}

.sensor-chart__x {
  display: flex;
  justify-content: space-between;
  /* bündig mit der Zeichenfläche (rechts neben der y-Beschriftung) */
  margin: var(--space-1) 0 0 calc(2.25em + var(--space-2));
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  color: var(--sub);
}
</style>
