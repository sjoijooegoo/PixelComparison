<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  series: { type: Array, required: true },
  points: { type: Array, default: () => [] },
  emptyLabel: { type: String, default: '当前范围' },
  currentBatchId: { type: [String, Number], default: '' },
  storageKey: { type: String, required: true },
})

const DEFAULT_WIDTH = 1200
const HEIGHT = 255
const HORIZONTAL_GUTTER = 52
const PLOT = { left: HORIZONTAL_GUTTER, right: HORIZONTAL_GUTTER, top: 14, bottom: 31 }
const chartCanvas = ref(null)
const chartWidth = ref(DEFAULT_WIDTH)
const plotWidth = computed(() => chartWidth.value - PLOT.left - PLOT.right)
const plotHeight = HEIGHT - PLOT.top - PLOT.bottom
const hoveredIndex = ref(null)
const blockedKey = ref('')
let blockedTimer = null
let resizeObserver = null

function loadVisibleKeys() {
  const defaults = props.series.map((item) => item.key)
  if (typeof window === 'undefined') return defaults
  try {
    const stored = JSON.parse(window.localStorage.getItem(props.storageKey))
    const visible = defaults.filter((key) => Array.isArray(stored) && stored.includes(key))
    return visible.length ? visible : defaults
  } catch {
    return defaults
  }
}

const visibleKeys = ref(loadVisibleKeys())
const visibleKeySet = computed(() => new Set(visibleKeys.value))
const visibleSeries = computed(() => props.series.filter((item) => visibleKeySet.value.has(item.key)))

function toggleSeries(key) {
  if (visibleKeys.value.length === 1 && visibleKeySet.value.has(key)) {
    blockedKey.value = key
    window.clearTimeout(blockedTimer)
    blockedTimer = window.setTimeout(() => { blockedKey.value = '' }, 1000)
    return
  }
  blockedKey.value = ''
  visibleKeys.value = visibleKeySet.value.has(key)
    ? visibleKeys.value.filter((item) => item !== key)
    : props.series.filter((item) => item.key === key || visibleKeySet.value.has(item.key))
      .map((item) => item.key)
  try {
    window.localStorage.setItem(props.storageKey, JSON.stringify(visibleKeys.value))
  } catch {
    // 浏览器禁用存储时仍保留本次页面会话内的选择。
  }
}

function metricValue(point, key) {
  const rawValue = point.metrics?.[key]
  if (rawValue == null) return null
  const value = Number(rawValue)
  return Number.isFinite(value) ? value : null
}

const chartSeries = computed(() => visibleSeries.value.map((item) => ({
  ...item,
  values: props.points.map((point) => metricValue(point, item.key)),
})))

function niceMaximum(value) {
  if (!Number.isFinite(value) || value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const normalized = value / magnitude
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return step * magnitude
}

const maximum = computed(() => niceMaximum(Math.max(
  ...chartSeries.value.flatMap((item) => item.values.filter((value) => value != null)),
  0,
)))
const ticks = computed(() => Array.from({ length: 5 }, (_, index) => maximum.value * index / 4))
const hasValues = computed(() => chartSeries.value.some((item) => item.values.some((value) => value != null)))
const hoveredPoint = computed(() => (
  hoveredIndex.value == null ? null : props.points[hoveredIndex.value]
))

function xAt(index) {
  if (props.points.length <= 1) return PLOT.left + plotWidth.value / 2
  return PLOT.left + index * plotWidth.value / (props.points.length - 1)
}

function yAt(value) {
  return PLOT.top + plotHeight - value / maximum.value * plotHeight
}

function pathFor(values) {
  let drawing = false
  return values.map((value, index) => {
    if (value == null) {
      drawing = false
      return ''
    }
    const command = drawing ? 'L' : 'M'
    drawing = true
    return `${command} ${xAt(index)} ${yAt(value)}`
  }).filter(Boolean).join(' ')
}

function bandStart(index) {
  if (props.points.length <= 1) return PLOT.left
  return index === 0 ? PLOT.left : (xAt(index - 1) + xAt(index)) / 2
}

function bandWidth(index) {
  if (props.points.length <= 1) return plotWidth.value
  const end = index === props.points.length - 1
    ? chartWidth.value - PLOT.right
    : (xAt(index) + xAt(index + 1)) / 2
  return end - bandStart(index)
}

function xLabelVisible(index) {
  if (index === props.points.length - 1) return true
  const step = Math.max(1, Math.ceil(props.points.length / 8))
  return index % step === 0
}

const dayCounts = computed(() => props.points.reduce((counts, point) => {
  const day = String(point.captured_at || '').slice(0, 10)
  counts.set(day, (counts.get(day) || 0) + 1)
  return counts
}, new Map()))

function shortDate(value) {
  const text = String(value || '')
  const day = text.slice(0, 10)
  const date = text.slice(5, 10)
  return (dayCounts.value.get(day) || 0) > 1 ? `${date} ${text.slice(11, 16)}` : date
}

function fullDate(value) {
  return String(value || '').replace('T', ' ').slice(0, 16) || '时间未知'
}

function formatValue(value) {
  if (value == null) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

function formatAxis(value) {
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1,
  }).format(value)
}

const tooltipStyle = computed(() => {
  if (hoveredIndex.value == null) return {}
  const percentage = xAt(hoveredIndex.value) / chartWidth.value * 100
  return { left: `${Math.max(9, Math.min(91, percentage))}%` }
})

function syncChartWidth(rect = chartCanvas.value?.getBoundingClientRect()) {
  if (!rect || rect.width <= 0 || rect.height <= 0) return
  chartWidth.value = Math.max(640, Math.round(HEIGHT * rect.width / rect.height))
}

watch(chartCanvas, (element) => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!element) return
  syncChartWidth(element.getBoundingClientRect())
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(([entry]) => syncChartWidth(entry.contentRect))
  resizeObserver.observe(element)
}, { flush: 'post' })
onBeforeUnmount(() => {
  window.clearTimeout(blockedTimer)
  resizeObserver?.disconnect()
})
</script>

<template>
  <article class="trend-card">
    <header>
      <div class="trend-heading">
        <strong>{{ title }}</strong>
        <div class="series-selector" role="group" :aria-label="`${title}显示指标`">
          <button v-for="item in series" :key="item.key" type="button"
            :class="{ active: visibleKeySet.has(item.key), blocked: blockedKey === item.key }"
            :aria-pressed="visibleKeySet.has(item.key)" :style="{ '--series-color': item.color }"
            :title="visibleKeys.length === 1 && visibleKeySet.has(item.key) ? '至少保留一项指标' : undefined"
            @click="toggleSeries(item.key)">
            <i></i>{{ item.label }}
            <span v-if="blockedKey === item.key">至少保留一项</span>
          </button>
        </div>
      </div>
    </header>

    <div v-if="hasValues" ref="chartCanvas" class="chart-canvas" @mouseleave="hoveredIndex = null">
      <svg :viewBox="`0 0 ${chartWidth} ${HEIGHT}`" role="img" :aria-label="`${title}版本趋势折线图`">
        <g v-for="tick in ticks" :key="tick">
          <line :x1="PLOT.left" :x2="chartWidth - PLOT.right"
            :y1="yAt(tick)" :y2="yAt(tick)" class="grid-line" />
          <text :x="PLOT.left - 10" :y="yAt(tick) + 4" text-anchor="end" class="axis-label">
            {{ formatAxis(tick) }}
          </text>
        </g>

        <line :x1="PLOT.left" :x2="chartWidth - PLOT.right"
          :y1="PLOT.top + plotHeight" :y2="PLOT.top + plotHeight" class="axis-line" />

        <g v-for="item in chartSeries" :key="item.key">
          <path v-if="pathFor(item.values)" :d="pathFor(item.values)" fill="none"
            :stroke="item.color" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
          <circle v-for="(value, index) in item.values" v-show="value != null"
            :key="`${item.key}-${index}`" :cx="xAt(index)" :cy="yAt(value || 0)"
            r="3.2" :fill="item.color" class="series-dot"
            :class="{
              current: String(points[index]?.batch_id) === String(currentBatchId),
            }" />
        </g>

        <line v-if="hoveredIndex != null" :x1="xAt(hoveredIndex)" :x2="xAt(hoveredIndex)"
          :y1="PLOT.top" :y2="PLOT.top + plotHeight" class="cursor-line" />

        <g v-for="(point, index) in points" :key="`axis-${point.batch_id}-${point.captured_at}`">
          <text v-if="xLabelVisible(index)" :x="xAt(index)" :y="HEIGHT - 11"
            text-anchor="middle" class="x-label">{{ shortDate(point.captured_at) }}</text>
          <rect :x="bandStart(index)" :y="PLOT.top" :width="bandWidth(index)"
            :height="plotHeight" fill="transparent" class="point-hit-area"
            @mouseenter="hoveredIndex = index" />
        </g>
      </svg>

      <div v-if="hoveredPoint" class="chart-tooltip" :style="tooltipStyle">
        <time :datetime="hoveredPoint.captured_at">{{ fullDate(hoveredPoint.captured_at) }}</time>
        <div class="tooltip-meta">
          <span>P4 {{ hoveredPoint.p4_version ?? '—' }}</span>
          <i>·</i>
          <span>批次 {{ hoveredPoint.batch_id ?? '—' }}</span>
        </div>
        <div v-for="item in visibleSeries" :key="item.key" class="tooltip-value">
          <span><i :style="{ backgroundColor: item.color }"></i>{{ item.label }}</span>
          <b>{{ formatValue(metricValue(hoveredPoint, item.key)) }}</b>
        </div>
      </div>
    </div>
    <div v-else class="trend-empty">{{ emptyLabel }}没有可显示的指标</div>
  </article>
</template>

<style scoped>
.trend-card {
  min-width: 0; min-height: 0; height: 100%; padding: 9px 11px 5px; overflow: hidden;
  box-sizing: border-box; display: flex; flex-direction: column;
  border: 1px solid var(--color-border-1); border-radius: 7px;
  background: color-mix(in srgb, var(--color-fill-1) 72%, transparent);
}
header {
  min-height: 28px; padding: 0 4px 4px; display: flex; align-items: center;
  gap: 12px; flex-wrap: wrap;
}
.trend-heading { min-width: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 5px 13px; }
.trend-heading > strong { color: var(--color-text-2); font-size: 14px; font-weight: 600; }
.series-selector {
  min-height: 24px; padding: 0;
  display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px;
}
.series-selector button {
  position: relative; padding: 2px 5px; display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid transparent; border-radius: 5px; background: transparent;
  color: var(--color-text-4); font-family: inherit; font-size: 11px; line-height: 1.25;
  cursor: pointer; opacity: .52;
  transition: color .12s ease, background-color .12s ease, border-color .12s ease,
    opacity .12s ease, transform .08s ease;
}
.series-selector button:hover { color: var(--color-text-2); opacity: .82; background: var(--color-fill-1); }
.series-selector button:active { transform: translateY(1px) scale(.97); background: var(--color-fill-2); }
.series-selector button.active {
  color: var(--color-text-3); opacity: 1;
  border-color: color-mix(in srgb, var(--series-color) 18%, transparent);
  background: color-mix(in srgb, var(--series-color) 7%, transparent);
}
.series-selector button.active:hover { background: color-mix(in srgb, var(--series-color) 11%, transparent); }
.series-selector button:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .75); outline-offset: 1px; }
.series-selector button > i {
  width: 14px; height: 3px; border-radius: 2px; background: var(--series-color);
  box-shadow: 0 0 8px color-mix(in srgb, currentColor 24%, transparent);
  transform-origin: left center; transition: opacity .12s ease, transform .12s ease;
}
.series-selector button:not(.active) > i { opacity: .38; transform: scaleX(.68); }
.series-selector button > span {
  position: absolute; left: 50%; top: calc(100% + 5px); z-index: 5; width: max-content;
  padding: 3px 6px; transform: translateX(-50%); border-radius: 4px;
  border: 1px solid rgba(var(--orange-6), .32); background: var(--color-bg-5);
  color: rgb(var(--orange-5)); font-size: 10px; pointer-events: none;
}
.series-selector button.blocked { animation: blocked-shake .26s ease; }
.chart-canvas { position: relative; flex: 1; min-height: 0; overflow: visible; }
svg { display: block; width: 100%; height: 100%; overflow: visible; }
.grid-line { stroke: var(--color-border-1); stroke-width: 1; vector-effect: non-scaling-stroke; }
.axis-line { stroke: var(--color-border-3); stroke-width: 1; vector-effect: non-scaling-stroke; }
.axis-label, .x-label {
  fill: var(--color-text-4); font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 8.5px; font-variant-numeric: tabular-nums;
}
.axis-label {
  pointer-events: none;
}
.x-label { font-size: 8px; }
.series-dot {
  stroke: var(--color-bg-2); stroke-width: 1.4; vector-effect: non-scaling-stroke;
}
.series-dot.current { stroke: rgba(255, 255, 255, .72); stroke-width: 1.2; }
.cursor-line {
  stroke: var(--color-text-3); stroke-width: 1; stroke-dasharray: 4 4;
  vector-effect: non-scaling-stroke; pointer-events: none;
}
.point-hit-area { cursor: crosshair; }
.chart-tooltip {
  position: absolute; top: 7px; z-index: 3; transform: translateX(-50%); width: 200px;
  padding: 10px 11px; border: 1px solid var(--color-border-3); border-radius: 7px;
  background: color-mix(in srgb, var(--color-bg-5) 94%, transparent);
  box-shadow: 0 10px 28px rgba(0, 0, 0, .28); backdrop-filter: blur(8px);
  pointer-events: none;
}
.chart-tooltip time {
  display: block; color: rgb(var(--arcoblue-5));
  font: 600 12px/1.35 "Bahnschrift", "Segoe UI", sans-serif;
}
.tooltip-meta {
  margin-top: 3px; padding-bottom: 7px; display: flex; align-items: center; gap: 5px;
  border-bottom: 1px solid var(--color-border-2); color: var(--color-text-2);
  font: 600 10px/1.35 "Bahnschrift", "Segoe UI", sans-serif;
}
.tooltip-meta i { color: var(--color-text-4); font-style: normal; font-weight: 400; }
.tooltip-value {
  padding-top: 6px; display: flex; align-items: center; justify-content: space-between;
  gap: 10px; color: var(--color-text-3); font-size: 11px;
}
.tooltip-value span { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.tooltip-value span i { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; }
.tooltip-value b {
  color: var(--color-text-1); font: 600 11px/1 "Bahnschrift", "Segoe UI", sans-serif;
  font-variant-numeric: tabular-nums;
}
.trend-empty { flex: 1; min-height: 0; display: grid; place-items: center; color: var(--color-text-3); }
@keyframes blocked-shake {
  0%, 100% { transform: translateX(0); }
  35% { transform: translateX(-2px); }
  70% { transform: translateX(2px); }
}
@media (prefers-reduced-motion: reduce) {
  .series-selector button, .series-dot { transition: none; }
  .series-selector button.blocked { animation: none; }
}
</style>
