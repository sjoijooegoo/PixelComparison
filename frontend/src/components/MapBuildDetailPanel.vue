<script setup>
import { computed } from 'vue'
import {
  formatMiB,
  rankMetricDetails,
} from '../mapBuildPresentation'
import { vOverflowTitle } from '../directives/overflowTitle'
import MapBuildMetricDelta from './MapBuildMetricDelta.vue'

const props = defineProps({
  detail: { type: Object, required: true },
  comparisonProps: { type: Object, required: true },
})

const rows = computed(() => rankMetricDetails(
  props.detail.metrics,
  props.detail.comparisonMetrics,
))
const maximum = computed(() => rows.value[0]?.value || 0)

function barWidth(value) {
  if (!maximum.value || !value) return '0%'
  return `${Math.max(3, value * 100 / maximum.value)}%`
}

function formatCount(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}
</script>

<template>
  <aside class="detail-panel card" aria-live="polite">
    <header class="detail-head">
      <div class="detail-title">
        <h3>{{ detail.label }}<small v-if="detail.effectiveScope === 'subtree'">（含子级汇总）</small></h3>
        <p v-overflow-title="detail.context">{{ detail.context }}</p>
      </div>
    </header>
    <div class="detail-summary">
      <div>
        <span>总 Mip</span>
        <span class="summary-value-line">
          <b>{{ formatMiB(detail.metrics.all_mips_bytes) }}</b>
          <MapBuildMetricDelta v-bind="comparisonProps"
            :current-value="detail.metrics.all_mips_bytes"
            :previous-value="detail.comparisonMetrics?.all_mips_bytes" />
        </span>
      </div>
      <div>
        <span>Cook 估算</span>
        <span class="summary-value-line">
          <b>{{ formatMiB(detail.metrics.cook_estimate_bytes) }}</b>
          <MapBuildMetricDelta v-bind="comparisonProps"
            :current-value="detail.metrics.cook_estimate_bytes"
            :previous-value="detail.comparisonMetrics?.cook_estimate_bytes" />
        </span>
      </div>
      <div>
        <span>纹理数</span>
        <span class="summary-value-line">
          <b>{{ formatCount(detail.metrics.texture_count) }}</b>
          <MapBuildMetricDelta v-bind="comparisonProps" value-kind="count"
            :current-value="detail.metrics.texture_count"
            :previous-value="detail.comparisonMetrics?.texture_count" />
        </span>
      </div>
    </div>
    <div class="detail-section-title">
      <span>指标明细</span>
      <small>从高到低</small>
    </div>
    <ol class="detail-list">
      <li v-for="(row, index) in rows" :key="row.key" class="detail-row">
        <div class="detail-row-head">
          <span><i>{{ String(index + 1).padStart(2, '0') }}</i>{{ row.label }}</span>
          <span class="detail-row-value">
            <MapBuildMetricDelta v-bind="comparisonProps"
              :current-value="row.value" :previous-value="row.previousValue" />
            <b>{{ formatMiB(row.value) }}</b>
          </span>
        </div>
        <div class="detail-track" aria-hidden="true">
          <i :style="{ width: barWidth(row.value), backgroundColor: row.color }"></i>
        </div>
      </li>
    </ol>
  </aside>
</template>

<style scoped>
.detail-panel {
  min-width: 0; overflow: hidden; display: flex; flex-direction: column;
  background: color-mix(in srgb, var(--color-bg-2) 94%, var(--color-fill-1));
}
.detail-head { padding: 15px 16px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--color-border-2); }
.detail-title { min-width: 0; }
.detail-head h3 { margin: 0; color: var(--color-text-1); font-size: 16px; line-height: 1.35; }
.detail-head h3 small { color: var(--color-text-3); font-size: 11px; font-weight: 500; }
.detail-head p { margin: 5px 0 0; overflow: hidden; color: var(--color-text-4); font: 11px/1.4 "Bahnschrift", "Segoe UI", sans-serif; text-overflow: ellipsis; white-space: nowrap; }
.detail-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-bottom: 1px solid var(--color-border-2); }
.detail-summary > div { min-height: 76px; padding: 12px 16px; display: flex; flex-direction: column; justify-content: center; }
.detail-summary > div + div { border-left: 1px solid var(--color-border-2); }
.detail-summary > div > span:first-child { color: var(--color-text-4); font-size: 12px; }
.summary-value-line { margin-top: 6px; display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.summary-value-line > b { color: var(--color-text-1); font: 600 15px/1.2 "Bahnschrift", "Segoe UI", sans-serif; }
.detail-section-title { padding: 12px 16px 7px; display: flex; align-items: baseline; justify-content: space-between; }
.detail-section-title span { color: var(--color-text-2); font-size: 13px; font-weight: 600; }
.detail-section-title small { color: var(--color-text-4); font-size: 10px; }
.detail-list { flex: 1; margin: 0; padding: 0 16px 9px; display: flex; flex-direction: column; justify-content: space-evenly; list-style: none; }
.detail-row { padding: 7px 0; }
.detail-row-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.detail-row-head > span:first-child { min-width: 0; overflow: hidden; color: var(--color-text-3); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.detail-row-head > span:first-child i { width: 25px; display: inline-block; color: var(--color-text-4); font: normal 10px "Bahnschrift", sans-serif; }
.detail-row-value { min-width: 118px; flex: 0 0 auto; display: grid; grid-template-columns: 48px minmax(68px, 1fr); align-items: baseline; gap: 0; }
.detail-row-value > b { color: var(--color-text-2); font: 600 12px "Bahnschrift", "Segoe UI", sans-serif; text-align: right; }
.detail-track { height: 3px; margin: 6px 0 0 25px; overflow: hidden; border-radius: 2px; background: var(--color-fill-3); }
.detail-track i { height: 100%; display: block; border-radius: inherit; opacity: .9; transition: width .18s ease; }
</style>
