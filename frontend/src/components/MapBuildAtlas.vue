<script setup>
import { computed } from 'vue'
import { atlasColor, formatMiB } from '../mapBuildPresentation'
import MapBuildMetricDelta from './MapBuildMetricDelta.vue'

const props = defineProps({
  overview: { type: Object, default: null },
  loading: Boolean,
  selectionKey: { type: String, default: 'world' },
  metricScope: { type: String, default: 'self' },
  comparisonProps: { type: Object, required: true },
})
const emit = defineEmits(['select', 'selectAuxiliary', 'changeMetricScope'])

const hasBlockTree = computed(() => (
  (props.overview?.blocks?.length || 0) + (props.overview?.auxiliary_blocks?.length || 0)
) > 0)
const maximumCellMipBytes = computed(() => Math.max(
  0,
  ...(props.overview?.blocks?.flatMap((block) => block.sub_blocks) || [])
    .map((cell) => Number(
      cell.self_metrics?.all_mips_bytes ?? cell.metrics?.all_mips_bytes ?? 0,
    ))
    .filter(Number.isFinite),
))

function keyFor(blockIndex = null, subBlockIndex = null) {
  return blockIndex === null ? 'world' : `${blockIndex}:${subBlockIndex ?? 'block'}`
}

function isSelected(blockIndex = null, subBlockIndex = null) {
  return props.selectionKey === keyFor(blockIndex, subBlockIndex)
}

function isAuxiliarySelected(path) {
  return props.selectionKey === `registry:${path}`
}

function nodeScope(node) {
  if (props.metricScope === 'subtree' && node?.subtree_metrics) return 'subtree'
  return node?.self_metrics ? 'self' : 'subtree'
}

function nodeMetrics(node) {
  return nodeScope(node) === 'self'
    ? node.self_metrics || node.metrics
    : node.subtree_metrics || node.metrics
}

function comparisonMetrics(node) {
  return node?.comparison_metrics?.[nodeScope(node)] || null
}

function scopeLabel(scope) {
  return scope === 'self' ? '仅自身' : '含子级汇总'
}
</script>

<template>
  <section class="atlas-card card" :class="{
    'world-selected': overview && isSelected()
      && (metricScope === 'subtree' || !overview.world?.has_children),
    'self-head-selected': overview && isSelected()
      && metricScope === 'self' && overview.world?.has_children,
  }">
    <button type="button" class="atlas-head world-head" :class="{ selected: isSelected() }"
      :aria-pressed="isSelected()" @click="emit('select', null, null)">
      <span class="world-select">
        <span class="section-stripe"></span>
        <b>主分块</b>
      </span>
      <span v-if="overview" class="world-total">
        <span>
          <small>{{ scopeLabel(nodeScope(overview.world)) }}</small>
          <span class="metric-value-line">
            <MapBuildMetricDelta v-bind="comparisonProps"
              :current-value="nodeMetrics(overview.world)?.all_mips_bytes"
              :previous-value="comparisonMetrics(overview.world)?.all_mips_bytes" />
            <b>{{ formatMiB(nodeMetrics(overview.world)?.all_mips_bytes) }}</b>
          </span>
        </span>
      </span>
    </button>

    <div v-if="loading && !overview" class="atlas-loading"><a-spin tip="正在整理分块…" /></div>
    <div v-else-if="overview && !hasBlockTree" class="no-block-tree" role="status">
      该场景没有分块数据，仅展示主分块数据
    </div>
    <div v-else-if="overview?.blocks?.length" class="block-layout">
      <article v-for="block in overview.blocks" :key="block.index" class="block-panel"
        :class="{
          selected: isSelected(block.index) && (metricScope === 'subtree' || !block.has_children),
          'self-head-selected': isSelected(block.index) && metricScope === 'self' && block.has_children,
        }">
        <button class="block-head" :class="{ selected: isSelected(block.index) }"
          :aria-pressed="isSelected(block.index)"
          @click="emit('select', block.index, null)">
          <span><i></i>{{ block.label }}</span>
          <span class="block-values">
            <small>{{ scopeLabel(nodeScope(block)) }}</small>
            <span class="metric-value-line">
              <MapBuildMetricDelta v-bind="comparisonProps"
                :current-value="nodeMetrics(block)?.all_mips_bytes"
                :previous-value="comparisonMetrics(block)?.all_mips_bytes" />
              <b>{{ formatMiB(nodeMetrics(block)?.all_mips_bytes) }}</b>
            </span>
          </span>
        </button>
        <div class="sub-grid">
          <button v-for="cell in block.sub_blocks" :key="cell.index" class="sub-cell"
            :class="{ selected: isSelected(block.index, cell.index) }"
            :style="{ backgroundColor: atlasColor(cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes, maximumCellMipBytes) }"
            :aria-pressed="isSelected(block.index, cell.index)"
            @click="emit('select', block.index, cell.index)">
            <span>{{ cell.label }}</span>
            <b>{{ formatMiB(cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes) }}</b>
            <MapBuildMetricDelta v-bind="comparisonProps"
              :current-value="cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes"
              :previous-value="cell.comparison_metrics?.self?.all_mips_bytes" />
          </button>
        </div>
      </article>
    </div>
    <footer v-if="overview && hasBlockTree" class="atlas-card-footer"
      :class="{ 'auxiliary-only': !overview.blocks?.length }">
      <div v-if="overview.auxiliary_blocks?.length" class="auxiliary-block-list">
        <button v-for="block in overview.auxiliary_blocks" :key="block.key || block.path"
          type="button" class="auxiliary-block"
          :class="{ selected: isAuxiliarySelected(block.path) }"
          :aria-pressed="isAuxiliarySelected(block.path)"
          @click="emit('selectAuxiliary', block.path)">
          <span><i></i><b>{{ block.label }}</b></span>
          <span class="auxiliary-values">
            <b>{{ formatMiB(nodeMetrics(block)?.all_mips_bytes) }}</b>
            <MapBuildMetricDelta v-bind="comparisonProps"
              :current-value="nodeMetrics(block)?.all_mips_bytes"
              :previous-value="comparisonMetrics(block)?.all_mips_bytes" />
          </span>
        </button>
      </div>
      <div class="atlas-scope-control">
        <div class="metric-scope-switch" role="group" aria-label="分块网格统计口径">
          <button type="button" :class="{ active: metricScope === 'self' }"
            :aria-pressed="metricScope === 'self'" @click="emit('changeMetricScope', 'self')">
            仅自身
          </button>
          <button type="button" :class="{ active: metricScope === 'subtree' }"
            :aria-pressed="metricScope === 'subtree'" @click="emit('changeMetricScope', 'subtree')">
            含子级
          </button>
        </div>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.atlas-card { min-width: 0; overflow: hidden; display: flex; flex-direction: column; transition: border-color .14s ease, box-shadow .14s ease; }
.atlas-card.world-selected { border-color: rgba(var(--arcoblue-6), .9); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .18), 0 0 0 1px rgba(var(--arcoblue-6), .3), 0 0 14px rgba(var(--arcoblue-6), .1); }
.atlas-card.self-head-selected > .world-head { position: relative; z-index: 1; border-top-left-radius: inherit; border-top-right-radius: inherit; background: color-mix(in srgb, rgb(var(--arcoblue-6)) 7%, transparent); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .78), 0 0 12px rgba(var(--arcoblue-6), .12); }
.atlas-scope-control { grid-column: 2; justify-self: end; flex: 0 0 auto; display: flex; align-items: center; }
.atlas-head { min-height: 58px; padding: 0 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--color-border-1); }
.world-head { box-sizing: border-box; width: 100%; flex: 0 0 auto; padding-right: 8px; border: 0; border-bottom: 1px solid var(--color-border-1); background: transparent; color: var(--color-text-1); font: inherit; text-align: left; cursor: pointer; transition: background-color .14s ease; }
.world-head:hover { background: var(--color-fill-1); }
.world-head:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .85); outline-offset: -3px; }
.world-head.selected { border-bottom-color: rgba(var(--arcoblue-6), .48); }
.world-select { min-width: 0; align-self: stretch; flex: 1 1 auto; display: flex; align-items: center; gap: 10px; padding: 6px 0; }
.section-stripe { width: 3px; height: 32px; border-radius: 2px; background: var(--color-border-3); }
.world-head.selected .section-stripe { background: rgb(var(--arcoblue-6)); box-shadow: 0 0 12px rgba(var(--arcoblue-6), .35); }
.world-select b { display: block; font-size: 15px; }
.world-total { min-width: 66px; align-self: stretch; padding: 5px 0 5px 4px; display: flex; align-items: center; justify-content: flex-end; color: inherit; font-family: "Bahnschrift", "Segoe UI", sans-serif; }
.world-total > span { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.world-total small { color: var(--color-text-4); font: 9px/1.2 "Segoe UI", sans-serif; }
.world-total b { color: var(--color-text-1); font-size: 13px; }
.metric-value-line { display: inline-flex; align-items: baseline; justify-content: flex-end; gap: 6px; }
.atlas-loading { min-height: 360px; display: grid; place-items: center; }
.no-block-tree { flex: 1 1 auto; min-height: 260px; display: grid; place-items: center; color: var(--color-text-3); font-size: 13px; text-align: center; }
.block-layout { min-width: 0; padding: 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.block-panel { min-width: 0; overflow: hidden; border: 1px solid var(--color-border-2); border-radius: 0; background: var(--color-fill-1); transition: border-color .14s ease, box-shadow .14s ease; }
.block-panel.selected { border-color: rgba(var(--arcoblue-6), .95); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .24), 0 0 0 1px rgba(var(--arcoblue-6), .38), 0 0 14px rgba(var(--arcoblue-6), .14); }
.block-panel.self-head-selected > .block-head { position: relative; z-index: 1; border-top-left-radius: inherit; border-top-right-radius: inherit; border-bottom-color: rgba(var(--arcoblue-6), .72); background: color-mix(in srgb, rgb(var(--arcoblue-6)) 7%, transparent); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .82), 0 0 10px rgba(var(--arcoblue-6), .12); }
.block-head { width: 100%; min-height: 42px; padding: 7px 11px; display: flex; align-items: center; justify-content: space-between; border: 0; border-bottom: 1px solid var(--color-border-2); background: color-mix(in srgb, var(--color-fill-2) 65%, transparent); color: var(--color-text-2); cursor: pointer; text-align: left; }
.block-head:hover, .block-head.selected { background: var(--color-fill-3); color: var(--color-text-1); }
.block-panel.selected .block-head { border-bottom-color: rgba(var(--arcoblue-6), .55); }
.block-head > span:first-child { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; }
.block-head i { width: 3px; height: 14px; border-radius: 2px; background: var(--color-border-3); }
.block-head.selected i { background: rgb(var(--arcoblue-6)); }
.block-values { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; font-family: "Bahnschrift", "Segoe UI", sans-serif; }
.block-values small { color: var(--color-text-4); font: 9px/1.1 "Segoe UI", sans-serif; }
.block-values b { font-size: 12px; }
.sub-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; background: transparent; }
.atlas-card-footer { min-height: 12px; margin-top: auto; padding: 0 12px 10px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: end; gap: 12px; }
.atlas-card-footer.auxiliary-only { padding-top: 12px; }
.auxiliary-block-list { min-width: 0; grid-column: 1; display: grid; gap: 8px; }
.auxiliary-block { box-sizing: border-box; width: 100%; min-height: 42px; padding: 7px 11px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid var(--color-border-2); border-radius: 0; background: color-mix(in srgb, var(--color-fill-2) 65%, transparent); color: var(--color-text-2); font: inherit; cursor: pointer; text-align: left; transition: color .14s ease, background-color .14s ease, border-color .14s ease, box-shadow .14s ease; }
.auxiliary-block:hover { background: var(--color-fill-3); color: var(--color-text-1); }
.auxiliary-block.selected { border-color: rgba(var(--arcoblue-6), .95); color: var(--color-text-1); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .24), 0 0 0 1px rgba(var(--arcoblue-6), .38), 0 0 14px rgba(var(--arcoblue-6), .14); }
.auxiliary-block:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .85); outline-offset: 2px; }
.auxiliary-block > span { min-width: 0; display: flex; align-items: center; gap: 7px; }
.auxiliary-block i { width: 3px; height: 14px; flex: 0 0 auto; border-radius: 2px; background: var(--color-border-3); }
.auxiliary-block.selected i { background: rgb(var(--arcoblue-6)); }
.auxiliary-block span b { overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.auxiliary-block > .auxiliary-values { min-width: 104px; flex: 0 0 auto; display: flex; align-items: baseline; justify-content: flex-end; gap: 8px; }
.auxiliary-block > .auxiliary-values > b { color: var(--color-text-1); font: 600 12px "Bahnschrift", "Segoe UI", sans-serif; }
.sub-cell { box-sizing: border-box; position: relative; min-height: 72px; padding: 10px 7px 8px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 0; color: rgba(255, 255, 255, .94); font-family: "Bahnschrift", "Segoe UI", sans-serif; cursor: pointer; contain: paint; transition: box-shadow .12s ease, transform .12s ease; }
.sub-cell:not(:nth-child(4n)) { border-right: 1px solid rgba(0,0,0,.26); }
.sub-cell:nth-child(-n+12) { border-bottom: 1px solid rgba(0,0,0,.26); }
.sub-cell:hover { background-image: linear-gradient(rgba(255,255,255,.055), rgba(255,255,255,.055)); }
.sub-cell:active { transform: scale(.985); }
.sub-cell.selected { z-index: 2; box-shadow: inset 0 0 0 2px #91bdff; }
.sub-cell > span:first-child { font-size: 11px; opacity: .78; }
.sub-cell b { margin-top: 3px; font-size: 12px; font-weight: 600; }
.sub-cell :deep(.metric-delta) { margin-top: 3px; justify-content: center; }
.sub-cell :deep(.metric-delta.is-steady), .sub-cell :deep(.metric-delta.is-unavailable) { color: rgba(255, 255, 255, .68); }
.metric-scope-switch { flex: 0 0 auto; padding: 1px; display: flex; gap: 2px; border: 1px solid var(--color-border-2); border-radius: 5px; background: var(--color-fill-1); }
.metric-scope-switch button { min-height: 23px; padding: 2px 8px; border: 0; border-radius: 4px; background: transparent; color: var(--color-text-3); font: 10px/1.2 "Segoe UI", sans-serif; cursor: pointer; transition: color .12s ease, background-color .12s ease, box-shadow .12s ease; }
.metric-scope-switch button:hover { color: var(--color-text-1); }
.metric-scope-switch button.active { color: rgb(var(--arcoblue-6)); background: color-mix(in srgb, rgb(var(--arcoblue-6)) 12%, var(--color-fill-2)); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .22); }
.metric-scope-switch button:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .78); outline-offset: 1px; }
@media (max-width: 680px) {
  .block-layout { grid-template-columns: 1fr; }
  .atlas-card-footer { grid-template-columns: 1fr; }
  .auxiliary-block-list, .atlas-scope-control { grid-column: 1; }
  .world-head { padding-right: 10px; }
  .sub-cell { min-height: 62px; }
}
</style>
