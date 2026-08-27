<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  metricKey: { type: String, required: true },
  points: { type: Array, default: () => [] },
  color: { type: String, default: '#3491fa' },
  available: { type: Boolean, default: true },
})

const chart = computed(() => {
  const source = props.points
    .map((point) => ({ ...point, value: Number(point.metrics?.[props.metricKey]) }))
    .filter((point) => Number.isFinite(point.value))
  if (!source.length) return { source, path: '', coordinates: [], min: 0, max: 0 }
  const values = source.map((point) => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || Math.max(Math.abs(max), 1)
  const coordinates = source.map((point, index) => ({
    ...point,
    x: source.length === 1 ? 50 : 5 + (index / (source.length - 1)) * 90,
    y: source.length === 1 ? 50 : 82 - ((point.value - min) / span) * 58,
  }))
  return {
    source, min, max, coordinates,
    path: coordinates.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' '),
  }
})

function compact(value) {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function day(value) {
  return String(value || '').slice(5, 10)
}
</script>

<template>
  <article class="trend-card card">
    <header><strong :style="{ color }">{{ title }}</strong><span>当前点位</span></header>
    <div v-if="chart.coordinates.length" class="chart-wrap">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <path v-for="line in [25, 45, 65, 85]" :key="line" :d="`M 5 ${line} H 96`" class="grid" />
        <path v-if="chart.coordinates.length > 1" :d="chart.path" class="line" :style="{ stroke: color }" />
        <circle v-for="point in chart.coordinates" :key="point.batch_id" :cx="point.x" :cy="point.y"
          r="1.35" :style="{ fill: color }" />
      </svg>
      <div class="values">
        <span v-for="point in chart.coordinates" :key="`value-${point.batch_id}`" class="value-label"
          :style="{ left: `${point.x}%`, top: `${Math.max(0, point.y * 1.74 - 18)}px` }">
          <b>{{ compact(point.value) }}</b>
        </span>
        <span v-for="point in chart.coordinates" :key="`axis-${point.batch_id}`" class="axis-label"
          :style="{ left: `${point.x}%` }">
          <small>{{ day(point.captured_at) }}<em>P4 {{ point.p4_version ?? '—' }}</em></small>
        </span>
      </div>
      <div v-if="!available" class="trend-note">仅显示当前批次；等待稳定 point_key 后形成跨批次趋势</div>
    </div>
    <div v-else class="trend-empty">当前点位没有该指标</div>
  </article>
</template>

<style scoped>
.trend-card { min-height: 260px; padding: 14px 16px 12px; }
header { display: flex; justify-content: space-between; align-items: center; }
header strong { font-size: 15px; }
header span { color: var(--color-text-3); font-size: 12px; }
.chart-wrap { position: relative; height: 210px; margin-top: 4px; }
svg { width: 100%; height: 174px; overflow: visible; }
.grid { stroke: var(--color-border-1); stroke-width: .35; vector-effect: non-scaling-stroke; }
.line { fill: none; stroke-width: 1.6; vector-effect: non-scaling-stroke; }
circle { vector-effect: non-scaling-stroke; stroke: var(--color-bg-2); stroke-width: 1; }
.values { position: absolute; inset: 0 0 auto; height: 194px; pointer-events: none; }
.values span { position: absolute; transform: translateX(-50%); text-align: center; white-space: nowrap; }
.value-label b { color: var(--color-text-2); font-size: 11px; font-weight: 500; }
.axis-label { bottom: -2px; }
.values small { display: flex; flex-direction: column; color: var(--color-text-3); font-size: 10px; font-variant-numeric: tabular-nums; }
.values em { color: var(--color-text-4); font-style: normal; font-size: 9px; }
.trend-note { position: absolute; left: 0; right: 0; bottom: -2px; text-align: center; color: var(--color-text-4); font-size: 11px; }
.trend-empty { height: 210px; display: grid; place-items: center; color: var(--color-text-3); }
</style>
