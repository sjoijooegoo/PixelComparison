<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  MAP_BUILD_SERIES,
  bytesToMiB,
  formatBytes,
  linePath,
  niceChartMaximum,
  trendAxisLabel,
  trendDayKey,
} from '../mapBuildPresentation'
import { p4Label } from '../store'

const props = defineProps({
  points: { type: Array, default: () => [] },
  currentBatchId: { type: [String, Number], default: '' },
})
const emit = defineEmits(['selectBatch'])

const WIDTH = 1200
const HEIGHT = 380
const HORIZONTAL_GUTTER = 52
const PLOT = { left: HORIZONTAL_GUTTER, right: HORIZONTAL_GUTTER, top: 24, bottom: 44 }
const POINT_HIT_RADIUS = 20
const plotWidth = WIDTH - PLOT.left - PLOT.right
const plotHeight = HEIGHT - PLOT.top - PLOT.bottom
const STORAGE_KEY = 'pixelcomp.mapBuildTrend.visibleSeries.v1'
const allSeriesKeys = MAP_BUILD_SERIES.map((series) => series.key)
const defaultSeriesKeys = MAP_BUILD_SERIES
  .filter((series) => series.defaultVisible)
  .map((series) => series.key)
const primarySeries = MAP_BUILD_SERIES.filter((series) => series.defaultVisible)
const optionalSeries = MAP_BUILD_SERIES.filter((series) => !series.defaultVisible)
const seriesGroups = [
  { className: 'legend-primary', label: '选择主要趋势指标', series: primarySeries },
  { className: 'legend-extra', label: '选择更多静态趋势指标', series: optionalSeries },
]
const hovered = ref(null)
const visibleSeriesKeys = ref(loadVisibleSeriesKeys())
const blockedSeriesKey = ref(null)
let blockedFeedbackTimer = null

function loadVisibleSeriesKeys() {
  if (typeof window === 'undefined') return defaultSeriesKeys
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY))
    if (!Array.isArray(stored)) return defaultSeriesKeys
    const visible = allSeriesKeys.filter((key) => stored.includes(key))
    return visible.length ? visible : defaultSeriesKeys
  } catch {
    return defaultSeriesKeys
  }
}

function saveVisibleSeriesKeys(keys) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
  } catch {
    // 浏览器禁用存储时仍保留当前会话内的选择。
  }
}

const visibleSeriesKeySet = computed(() => new Set(visibleSeriesKeys.value))
const visibleSeries = computed(() => MAP_BUILD_SERIES.filter(
  (series) => visibleSeriesKeySet.value.has(series.key),
))
function isSeriesVisible(key) {
  return visibleSeriesKeySet.value.has(key)
}

function isLastVisibleSeries(key) {
  return isSeriesVisible(key) && visibleSeriesKeys.value.length === 1
}

function showBlockedFeedback(key) {
  blockedSeriesKey.value = key
  window.clearTimeout(blockedFeedbackTimer)
  blockedFeedbackTimer = window.setTimeout(() => {
    blockedSeriesKey.value = null
  }, 1100)
}

function toggleSeries(key) {
  if (isLastVisibleSeries(key)) {
    showBlockedFeedback(key)
    return
  }
  blockedSeriesKey.value = null
  const nextKeys = isSeriesVisible(key)
    ? visibleSeriesKeys.value.filter((item) => item !== key)
    : allSeriesKeys.filter((item) => item === key || visibleSeriesKeySet.value.has(item))
  visibleSeriesKeys.value = nextKeys
  saveVisibleSeriesKeys(nextKeys)
}

function seriesToggleTitle(series) {
  if (isLastVisibleSeries(series.key)) return '至少保留一项趋势指标'
  return `${isSeriesVisible(series.key) ? '隐藏' : '显示'}${series.label}`
}

onBeforeUnmount(() => window.clearTimeout(blockedFeedbackTimer))

const chartSeries = computed(() => visibleSeries.value.map((series) => ({
  ...series,
  values: props.points.map((point) => (
    point.metrics ? bytesToMiB(point.metrics[series.key]) : null
  )),
})))
const maximum = computed(() => niceChartMaximum(
  chartSeries.value.flatMap((series) => series.values.filter((value) => value != null)),
))
const dayCounts = computed(() => props.points.reduce((counts, point) => {
  const day = trendDayKey(point)
  if (day) counts.set(day, (counts.get(day) || 0) + 1)
  return counts
}, new Map()))
const ticks = computed(() => Array.from({ length: 5 }, (_, index) => maximum.value * index / 4))

function xAt(index) {
  if (props.points.length <= 1) return PLOT.left + plotWidth / 2
  return PLOT.left + index * plotWidth / (props.points.length - 1)
}
function yAt(value) {
  return PLOT.top + plotHeight - value / maximum.value * plotHeight
}
function pathFor(values) {
  return linePath(values, xAt, yAt)
}
function xLabelVisible(index) {
  if (index === props.points.length - 1) return true
  const step = Math.max(1, Math.ceil(props.points.length / 8))
  return index % step === 0
}
function shortDate(point) {
  const day = trendDayKey(point)
  return trendAxisLabel(point, (dayCounts.value.get(day) || 0) > 1)
}
function fullDate(point) {
  return point?.batch?.created_at?.replace('T', ' ') || '—'
}
const hoverPoint = computed(() => (
  hovered.value === null ? null : props.points[hovered.value]
))
const selectedIndex = computed(() => props.points.findIndex(
  (point) => String(point?.batch?.id) === String(props.currentBatchId),
))
const tooltipStyle = computed(() => {
  if (hovered.value === null) return {}
  const pct = xAt(hovered.value) / WIDTH * 100
  return {
    left: `${Math.max(9, Math.min(91, pct))}%`,
  }
})

function pointAriaLabel(point) {
  return `${fullDate(point)}，批次 ${point?.batch?.id ?? '—'}，${p4Label(point?.batch?.p4_version)}，点击切换基线批次`
}

function selectPoint(point, index) {
  hovered.value = index
  if (point?.batch?.id === undefined || point?.batch?.id === null) return
  emit('selectBatch', point.batch)
}
</script>

<template>
  <div v-if="points.length" class="trend-chart" :style="{ '--plot-left': `${PLOT.left}px` }">
    <div v-for="group in seriesGroups" :key="group.className"
      class="legend" :class="group.className" role="group" :aria-label="group.label">
      <button v-for="series in group.series" :key="series.key" type="button" class="legend-item"
        :class="{ active: isSeriesVisible(series.key), blocked: blockedSeriesKey === series.key }"
        :aria-pressed="isSeriesVisible(series.key)" :style="{ '--series-color': series.color }"
        :aria-label="seriesToggleTitle(series)"
        :title="isLastVisibleSeries(series.key) ? '至少保留一项趋势指标' : undefined"
        @click="toggleSeries(series.key)">
        <i aria-hidden="true"></i>{{ series.label }}
        <span v-if="blockedSeriesKey === series.key" class="legend-limit" role="status">至少保留一项</span>
      </button>
    </div>
    <div class="canvas" @mouseleave="hovered = null">
      <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" role="img" aria-label="烘培数据批次趋势折线图">
        <text :x="PLOT.left - 10" :y="PLOT.top - 8" text-anchor="end" class="axis-unit">MiB</text>
        <g v-for="tick in ticks" :key="tick">
          <line :x1="PLOT.left" :x2="WIDTH - PLOT.right" :y1="yAt(tick)" :y2="yAt(tick)" class="grid-line" />
          <text :x="PLOT.left - 10" :y="yAt(tick) + 4" text-anchor="end" class="axis-label">
            {{ tick.toFixed(tick < 10 ? 2 : 0) }}
          </text>
        </g>

        <g v-for="series in chartSeries" :key="series.key">
          <path v-if="pathFor(series.values)" :d="pathFor(series.values)" fill="none"
            :stroke="series.color" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
          <circle v-for="(value, index) in series.values" v-show="value != null"
            :key="`${series.key}-${index}`" :cx="xAt(index)" :cy="yAt(value || 0)" r="3.2"
            :fill="series.color" class="series-dot"
            :class="{ 'current-batch-dot': index === selectedIndex }" />
        </g>

        <line v-if="hovered !== null" :x1="xAt(hovered)" :x2="xAt(hovered)"
          :y1="PLOT.top" :y2="PLOT.top + plotHeight" class="cursor-line" />

        <g v-for="(point, index) in points" :key="point.batch.id">
          <text v-if="xLabelVisible(index)" :x="xAt(index)" :y="HEIGHT - 14"
            text-anchor="middle" class="x-label">{{ shortDate(point) }}</text>
        </g>

        <g v-for="series in chartSeries" :key="`hit-${series.key}`">
          <circle v-for="(value, index) in series.values" v-show="value != null"
            :key="`hit-${series.key}-${index}`" :cx="xAt(index)" :cy="yAt(value || 0)"
            :r="POINT_HIT_RADIUS" class="point-hit-area" fill="transparent"
            focusable="false" :aria-label="pointAriaLabel(points[index])"
            @mouseenter="hovered = index" @mouseleave="hovered = null"
            @click="selectPoint(points[index], index)" />
        </g>
      </svg>

      <div v-if="hoverPoint" class="tooltip" :style="tooltipStyle">
        <div class="tooltip-title">
          <div class="tooltip-heading">
            <time class="tooltip-time" :datetime="hoverPoint.batch.created_at">
              {{ fullDate(hoverPoint) }}
            </time>
            <span>{{ p4Label(hoverPoint.batch.p4_version) }}</span>
          </div>
        </div>
        <div v-for="series in visibleSeries" :key="series.key" class="tooltip-row">
          <span><i :style="{ background: series.color }"></i>{{ series.label }}</span>
          <b>{{ hoverPoint.metrics ? formatBytes(hoverPoint.metrics[series.key]) : '该批次无此分块' }}</b>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="chart-empty">
    <span class="empty-mark">∿</span>
    当前筛选还没有可绘制的批次趋势
  </div>
</template>

<style scoped>
.trend-chart { min-width: 0; }
.legend {
  display: flex; flex-wrap: wrap; align-items: center; gap: 20px;
  padding: 2px 8px 8px var(--plot-left);
}
.legend-primary { row-gap: 7px; }
.legend-extra {
  margin: 0 8px 8px var(--plot-left); padding: 8px 10px; gap: 7px 12px;
  border-top: 1px solid var(--color-border-1);
  background: color-mix(in srgb, var(--color-fill-1) 38%, transparent);
}
.legend-item {
  position: relative; padding: 3px 6px; display: inline-flex; align-items: center; gap: 7px;
  border: 1px solid transparent;
  border-radius: 5px; background: transparent; color: var(--color-text-4); font: 12px/1.4 inherit;
  cursor: pointer; opacity: .52;
  transition: color .12s ease, background-color .12s ease, border-color .12s ease,
    opacity .12s ease, transform .08s ease;
}
.legend-item:hover { background: var(--color-fill-1); color: var(--color-text-2); opacity: .82; }
.legend-item:active { transform: translateY(1px) scale(.97); background: var(--color-fill-2); }
.legend-item.active {
  color: var(--color-text-3); opacity: 1;
  background: color-mix(in srgb, var(--series-color) 7%, transparent);
  border-color: color-mix(in srgb, var(--series-color) 18%, transparent);
}
.legend-item.active:hover { background: color-mix(in srgb, var(--series-color) 11%, transparent); }
.legend-item:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .78); outline-offset: 1px; }
.legend-item i {
  width: 14px; height: 3px; border-radius: 2px; background: var(--series-color);
  box-shadow: 0 0 8px color-mix(in srgb, currentColor 24%, transparent);
  transform-origin: left center; transition: opacity .12s ease, transform .12s ease;
}
.legend-item:not(.active) i { opacity: .38; transform: scaleX(.68); }
.legend-item.blocked { animation: legend-blocked .28s ease; }
.legend-limit {
  position: absolute; left: 50%; top: calc(100% + 6px); z-index: 4; transform: translateX(-50%);
  width: max-content; padding: 3px 7px; border: 1px solid rgba(var(--orange-6), .36); border-radius: 5px;
  background: color-mix(in srgb, var(--color-bg-5) 96%, transparent); color: rgb(var(--orange-5));
  box-shadow: 0 6px 18px rgba(0, 0, 0, .24); font-size: 10px; pointer-events: none;
}
@keyframes legend-blocked {
  0%, 100% { transform: translateX(0); }
  35% { transform: translateX(-2px); }
  70% { transform: translateX(2px); }
}
@media (prefers-reduced-motion: reduce) {
  .legend-item, .legend-item i { transition: none; }
  .legend-item.blocked { animation: none; }
}
.canvas { position: relative; min-height: 310px; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
.grid-line { stroke: var(--color-border-1); stroke-width: 1; }
.axis-label, .x-label { fill: var(--color-text-4); font-size: 11px; font-family: "Bahnschrift", "Segoe UI", sans-serif; }
.axis-unit {
  fill: var(--color-text-4); opacity: .72; font: 600 9.5px/1 "Bahnschrift", "Segoe UI", sans-serif;
  letter-spacing: .04em;
}
.x-label { font-size: 10px; }
.series-dot { stroke: var(--color-bg-2); stroke-width: 1.5; }
.series-dot.current-batch-dot {
  r: 4px; stroke: rgba(255, 255, 255, .96); stroke-width: 2;
  filter: drop-shadow(0 0 2px rgba(var(--arcoblue-5), .42));
}
.cursor-line { stroke: var(--color-text-3); stroke-width: 1; stroke-dasharray: 4 4; }
.point-hit-area { cursor: pointer; pointer-events: all; }
.tooltip {
  position: absolute; top: 20px; z-index: 3; transform: translateX(-50%); width: 250px;
  padding: 11px 12px; border-radius: 8px; pointer-events: none;
  background: color-mix(in srgb, var(--color-bg-5) 40%, transparent);
  border: 1px solid var(--color-border-3); box-shadow: 0 7px 18px rgba(0, 0, 0, .16);
  backdrop-filter: blur(5px);
}
.tooltip-title { padding-bottom: 8px; margin-bottom: 7px; border-bottom: 1px solid var(--color-border-2); }
.tooltip-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.tooltip-time {
  display: block; color: rgb(var(--arcoblue-5));
  font: 600 13px/1.3 "Bahnschrift", "Segoe UI", sans-serif; letter-spacing: .01em;
}
.tooltip-heading > span {
  flex: 0 0 auto; color: var(--color-text-2);
  font: 600 11px/1.3 "Bahnschrift", "Segoe UI", sans-serif; white-space: nowrap;
}
.tooltip-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 3px 0; color: var(--color-text-3); font-size: 11px; }
.tooltip-row span { display: inline-flex; align-items: center; gap: 6px; }
.tooltip-row i { width: 7px; height: 7px; border-radius: 50%; }
.tooltip-row b { color: var(--color-text-1); font-family: "Bahnschrift", "Segoe UI", sans-serif; font-weight: 600; }
.chart-empty { min-height: 250px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--color-text-4); }
.empty-mark { font-size: 32px; color: var(--color-text-4); }
</style>
