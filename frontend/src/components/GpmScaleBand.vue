<script setup>
import { computed } from 'vue'

import { formatMetricValue } from '../gpmHeatmap/colors'

const props = defineProps({
  thresholds: { type: Array, default: () => [] },
  colors: { type: Array, default: () => [] },
  labels: { type: Array, default: () => [] },
  direction: { type: String, default: 'lower_is_better' },
  compact: { type: Boolean, default: false },
})

const bands = computed(() => (props.colors || []).slice(0, 10).map((_, index, colors) => {
  const paletteIndex = props.direction === 'higher_is_better' ? colors.length - 1 - index : index
  return {
  color: colors[paletteIndex],
  label: props.labels?.[paletteIndex] || `等级 ${paletteIndex + 1}`,
  range: index === 0
    ? `< ${formatMetricValue(props.thresholds?.[0])}`
    : index === colors.length - 1
      ? `≥ ${formatMetricValue(props.thresholds?.[colors.length - 2])}`
      : `${formatMetricValue(props.thresholds?.[index - 1])} – ${formatMetricValue(props.thresholds?.[index])}`,
  }
}))
</script>

<template>
  <div class="scale-band" :class="{ compact }" :style="{ '--band-count': bands.length }">
    <div v-for="(band, index) in bands" :key="`${index}-${band.color}`" class="band" :style="{ '--band-color': band.color }">
      <i></i>
      <span v-if="!compact">{{ band.label }}</span>
      <small v-if="!compact">{{ band.range }}</small>
    </div>
  </div>
</template>

<style scoped>
.scale-band { display: grid; grid-template-columns: repeat(var(--band-count, 5), minmax(0, 1fr)); gap: 3px; }
.band { min-width: 0; display: grid; grid-template-columns: 12px minmax(0, 1fr); align-items: center; gap: 4px 6px; }
.band i { grid-row: 1 / 3; width: 12px; height: 30px; border-radius: 2px; background: var(--band-color); }
.band span { overflow: hidden; color: var(--color-text-2); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.band small { overflow: hidden; color: var(--color-text-4); font-size: 9px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.scale-band.compact { gap: 1px; }
.compact .band { display: block; }
.compact .band i { display: block; width: 100%; height: 7px; border-radius: 1px; }
</style>
