<script setup>
import { computed } from 'vue'
import {
  compareMetricValues,
  formatExactBytes,
  formatMetricDelta,
  formatMiB,
  mapBuildDeltaColor,
} from '../mapBuildPresentation'

const props = defineProps({
  currentValue: { type: [Number, String], default: null },
  previousValue: { type: [Number, String], default: null },
  enabled: { type: Boolean, default: false },
  baselineAvailable: { type: Boolean, default: false },
  comparisonLabel: { type: String, default: '对比批次' },
  percentRange: { type: Array, default: () => [0, 0] },
  valueKind: { type: String, default: 'bytes' },
})

const comparison = computed(() => compareMetricValues(
  props.currentValue,
  props.previousValue,
  props.baselineAvailable,
))
const displayValue = computed(() => formatMetricDelta(comparison.value))
const displayColor = computed(() => mapBuildDeltaColor(comparison.value, props.percentRange))

function formatValue(value) {
  if (props.valueKind === 'count') return Number(value || 0).toLocaleString('zh-CN')
  return formatMiB(value)
}

</script>

<template>
  <a-tooltip v-if="enabled" position="top">
    <span class="metric-delta" :class="`is-${comparison.kind}`"
      :style="{ color: displayColor }">{{ displayValue }}</span>
    <template #content>
      <div class="delta-tooltip">
        <div><span>当前</span><b :title="valueKind === 'bytes' ? formatExactBytes(comparison.current) : undefined">{{ formatValue(comparison.current) }}</b></div>
        <div v-if="comparison.kind !== 'unavailable'">
          <span>{{ comparisonLabel }}</span>
          <b v-if="comparison.previous !== null" :title="valueKind === 'bytes' ? formatExactBytes(comparison.previous) : undefined">
            {{ formatValue(comparison.previous) }}
          </b>
          <b v-else>无对应数据</b>
        </div>
      </div>
    </template>
  </a-tooltip>
</template>

<style scoped>
.metric-delta {
  min-width: 47px; display: inline-flex; align-items: center; justify-content: flex-end;
  color: rgba(255, 255, 255, .68); font: 600 11px/1.15 "Bahnschrift", "Segoe UI", sans-serif;
  white-space: nowrap;
}
.metric-delta.is-steady, .metric-delta.is-unavailable { color: var(--color-text-4); }
.delta-tooltip { min-width: 154px; display: grid; gap: 4px; font-size: 11px; line-height: 1.35; }
.delta-tooltip > div { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.delta-tooltip span { color: rgba(255, 255, 255, .62); }
.delta-tooltip b { color: rgba(255, 255, 255, .96); font-weight: 600; }
</style>
