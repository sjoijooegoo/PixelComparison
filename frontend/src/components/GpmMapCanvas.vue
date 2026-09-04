<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { createMapProjection, containedImageRect } from '../gpmHeatmap/mapProjection'
import { createPointHitIndex } from '../gpmHeatmap/pointHitIndex'
import {
  LINEAR_HEAT_GRADIENT,
  configuredBandIndex,
  configuredBands,
  formatCoordinateValue,
  formatConfiguredBandRange,
  metricRange,
  resolvedHeatColor,
} from '../gpmHeatmap/colors'

const props = defineProps({
  frame: { type: Object, default: null },
  metricKey: { type: String, default: 'Scene_DC' },
  selectedPointId: { type: [Number, String], default: null },
})
const emit = defineEmits(['select', 'metric'])

const TOOLTIP_SHOW_DELAY_MS = 200
const TOOLTIP_SWITCH_DELAY_MS = 150
const TOOLTIP_HIDE_DELAY_MS = 0

const host = ref(null)
const canvas = ref(null)
const mapImage = ref(null)
const hoveredPointId = ref(null)
const tooltipPointId = ref(null)
const tooltipAnchor = ref(null)
const hoveredBandIndex = ref(null)
const hiddenBandIndexes = ref(new Set())
let observer = null
let pointHitIndex = createPointHitIndex([])
let tooltipIntentTimer = null
let pendingTooltipPointId = null
let pendingTooltipAnchor = null
let hasPendingTooltip = false

const metric = computed(() => props.frame?.heat_map?.find((item) => item.key === props.metricKey))
const valueRange = computed(() => metricRange(props.frame?.points, props.metricKey))
const activeScale = computed(() => metric.value?.scale)
const scaleBands = computed(() => configuredBands(activeScale.value))
const pointsById = computed(() => new Map(
  (props.frame?.points || []).map((point) => [String(point.id), point]),
))
const tooltipPoint = computed(() => pointsById.value.get(String(tooltipPointId.value)))
const tooltipValue = computed(() => tooltipPoint.value?.heat_map_data?.[props.metricKey])
const tooltipChangePercent = computed(() => (
  tooltipPoint.value?.metric_change_percent?.[props.metricKey]
))
const tooltipValueColor = computed(() => resolvedHeatColor(
  tooltipValue.value,
  activeScale.value,
  valueRange.value,
))

function samePointId(left, right) {
  return left !== null && left !== undefined
    && right !== null && right !== undefined
    && String(left) === String(right)
}

function sameOptionalPointId(left, right) {
  const leftEmpty = left === null || left === undefined
  const rightEmpty = right === null || right === undefined
  return leftEmpty && rightEmpty ? true : samePointId(left, right)
}

function sameTooltipAnchor(left, right) {
  return left && right
    && left.x === right.x
    && left.y === right.y
    && left.side === right.side
}

function clearTooltipIntent() {
  if (tooltipIntentTimer !== null) window.clearTimeout(tooltipIntentTimer)
  tooltipIntentTimer = null
  pendingTooltipPointId = null
  pendingTooltipAnchor = null
  hasPendingTooltip = false
}

function requestTooltip(pointId, anchor) {
  const nextId = pointId ?? null
  if (sameOptionalPointId(nextId, tooltipPointId.value)) {
    clearTooltipIntent()
    if (nextId !== null && anchor && !sameTooltipAnchor(anchor, tooltipAnchor.value)) {
      tooltipAnchor.value = anchor
    }
    return
  }
  if (hasPendingTooltip && sameOptionalPointId(nextId, pendingTooltipPointId)) {
    pendingTooltipAnchor = anchor
    return
  }

  clearTooltipIntent()
  hasPendingTooltip = true
  pendingTooltipPointId = nextId
  pendingTooltipAnchor = anchor
  const delay = nextId === null
    ? TOOLTIP_HIDE_DELAY_MS
    : tooltipPointId.value === null
      ? TOOLTIP_SHOW_DELAY_MS
      : TOOLTIP_SWITCH_DELAY_MS
  tooltipIntentTimer = window.setTimeout(() => {
    const committedId = pendingTooltipPointId
    const committedAnchor = pendingTooltipAnchor
    clearTooltipIntent()
    tooltipPointId.value = committedId
    tooltipAnchor.value = committedId === null ? null : committedAnchor
  }, delay)
}

function resetHoverState() {
  clearTooltipIntent()
  hoveredPointId.value = null
  tooltipPointId.value = null
  tooltipAnchor.value = null
}

function formatValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value ?? '--'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number)
}

function changeIndicator(value) {
  if (value === null || value === undefined || String(value).trim() === '') {
    return { label: '—', direction: 'unavailable' }
  }
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return { label: '—', direction: 'unavailable' }
  }
  if (number !== 0 && Math.abs(number) < 0.1) {
    return { label: '≈0.0%', direction: 'flat' }
  }
  const percentage = new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: 1,
  }).format(Math.abs(number))
  if (number > 0) return { label: `↑ ${percentage}%`, direction: 'up' }
  if (number < 0) return { label: `↓ ${percentage}%`, direction: 'down' }
  return { label: '0%', direction: 'flat' }
}

const tooltipChange = computed(() => changeIndicator(tooltipChangePercent.value))

function setHoveredBand(index) {
  hoveredBandIndex.value = index
}

function toggleBand(index) {
  const next = new Set(hiddenBandIndexes.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  hiddenBandIndexes.value = next
}

function projectionForSize(width, height) {
  const config = props.frame?.map_config
  if (!config || !mapImage.value?.naturalWidth) return null
  const rect = containedImageRect(
    width, height, mapImage.value.naturalWidth, mapImage.value.naturalHeight,
  )
  return createMapProjection(config, rect)
}

function traceDirectionArrow(context, point, direction) {
  const startX = point.x
  const startY = point.y
  const endX = point.x + direction.x * 20
  const endY = point.y + direction.y * 20
  const angle = Math.atan2(direction.y, direction.x)
  const headLength = 5
  const headSpread = Math.PI / 5
  context.beginPath()
  context.moveTo(startX, startY)
  context.lineTo(endX, endY)
  context.moveTo(endX, endY)
  context.lineTo(
    endX - headLength * Math.cos(angle - headSpread),
    endY - headLength * Math.sin(angle - headSpread),
  )
  context.moveTo(endX, endY)
  context.lineTo(
    endX - headLength * Math.cos(angle + headSpread),
    endY - headLength * Math.sin(angle + headSpread),
  )
}

function drawDirectionArrow(context, point, direction) {
  context.save()
  context.lineCap = 'round'
  context.lineJoin = 'round'

  traceDirectionArrow(context, point, direction)
  context.strokeStyle = 'rgba(0, 0, 0, .72)'
  context.lineWidth = 4
  context.stroke()

  traceDirectionArrow(context, point, direction)
  context.strokeStyle = 'rgba(255, 255, 255, .96)'
  context.lineWidth = 1.7
  context.stroke()
  context.restore()
}

function drawPointSquare(context, item) {
  context.save()
  context.globalAlpha = item.alpha
  context.fillStyle = item.color
  context.fillRect(
    item.point.x - item.size / 2,
    item.point.y - item.size / 2,
    item.size,
    item.size,
  )
  context.strokeStyle = item.selected ? '#ffffff' : 'rgba(0,0,0,.72)'
  context.lineWidth = item.selected ? 2 : 1
  context.strokeRect(
    item.point.x - item.size / 2,
    item.point.y - item.size / 2,
    item.size,
    item.size,
  )
  context.restore()
}

function draw() {
  const element = canvas.value
  const container = host.value
  if (!element || !container) return
  const width = container.clientWidth
  const height = container.clientHeight
  const ratio = window.devicePixelRatio || 1
  const pixelWidth = Math.max(1, Math.round(width * ratio))
  const pixelHeight = Math.max(1, Math.round(height * ratio))
  if (element.width !== pixelWidth) element.width = pixelWidth
  if (element.height !== pixelHeight) element.height = pixelHeight
  if (element.style.width !== `${width}px`) element.style.width = `${width}px`
  if (element.style.height !== `${height}px`) element.style.height = `${height}px`
  const context = element.getContext('2d')
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, width, height)
  const projection = projectionForSize(width, height)
  if (!projection) {
    pointHitIndex = createPointHitIndex([])
    return
  }
  const projected = []
  const renderPoints = []
  for (const source of props.frame?.points || []) {
    const point = projection.project(source.position)
    if (!point.inBounds) continue
    const direction = projection.projectDirection(source.direction)
    const selected = samePointId(source.id, props.selectedPointId)
    const hovered = samePointId(source.id, hoveredPointId.value)
    const value = source.heat_map_data?.[props.metricKey]
    const bandIndex = configuredBandIndex(value, activeScale.value)
    if (hiddenBandIndexes.value.has(bandIndex)) continue
    const emphasizedByLegend = hoveredBandIndex.value !== null
      && bandIndex === hoveredBandIndex.value
    const dimmedByLegend = hoveredBandIndex.value !== null && !emphasizedByLegend
    const size = (selected ? 13 : hovered ? 12 : 10) + (emphasizedByLegend ? 4 : 0)
    const color = resolvedHeatColor(
      value, activeScale.value, valueRange.value,
    )
    renderPoints.push({
      point, direction, selected, hovered, size, color,
      alpha: dimmedByLegend ? 0.18 : 1,
    })
    projected.push({ source, x: point.x, y: point.y, hit: Math.max(13, size + 2) })
  }
  pointHitIndex = createPointHitIndex(projected)

  // 方块先统一绘制；活动箭头随后提升到所有普通点位之上，最后再覆盖活动
  // 点位自己的方块，确保箭头从方块下方伸出且不会被其他点位截断。
  renderPoints.forEach((item) => drawPointSquare(context, item))
  const activePoints = renderPoints.filter((item) => item.selected || item.hovered)
    // Canvas 后绘制的元素位于上层；悬停点必须排在选中点之后。
    .sort((left, right) => Number(left.hovered) - Number(right.hovered))
  const arrowPoints = props.frame?.map?.show_direction ? activePoints : []
  arrowPoints.forEach((item) => {
    context.save()
    context.globalAlpha = item.alpha
    drawDirectionArrow(context, item.point, item.direction)
    context.restore()
  })
  activePoints.forEach((item) => drawPointSquare(context, item))
}

function pointAtEvent(event) {
  const rect = canvas.value.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  return pointHitIndex.find(x, y)
}

function clickMap(event) {
  const nearest = pointAtEvent(event)
  if (nearest) emit('select', nearest.source.id)
}

function moveMap(event) {
  const nearest = pointAtEvent(event)
  const nextId = nearest?.source?.id ?? null
  const unchanged = nextId === null
    ? hoveredPointId.value === null
    : samePointId(nextId, hoveredPointId.value)
  canvas.value.style.cursor = nearest ? 'pointer' : 'default'
  const nextAnchor = nearest ? {
    x: nearest.x,
    y: nearest.y,
    side: nearest.x > canvas.value.clientWidth - 225 ? 'left' : 'right',
  } : null
  if (!unchanged) hoveredPointId.value = nextId
  requestTooltip(nextId, nextAnchor)
}

function leaveMap() {
  if (canvas.value) canvas.value.style.cursor = 'default'
  hoveredPointId.value = null
  requestTooltip(null, null)
}

function imageReady() {
  nextTick(draw)
}

// frame 由 store 以不可变响应对象整体替换，无需深度遍历可能很大的点位数组。
watch(() => props.frame, () => {
  resetHoverState()
  hoveredBandIndex.value = null
  hiddenBandIndexes.value = new Set()
})
watch(() => props.metricKey, () => {
  hoveredBandIndex.value = null
  hiddenBandIndexes.value = new Set()
})
watch(() => [
  props.frame,
  props.metricKey,
  props.selectedPointId,
  hoveredPointId.value,
  hoveredBandIndex.value,
  hiddenBandIndexes.value,
], draw)
watch(host, (element, previous) => {
  if (previous) observer?.unobserve(previous)
  if (element) {
    observer?.observe(element)
    draw()
  }
}, { flush: 'post' })
onMounted(() => {
  observer = new ResizeObserver(draw)
  if (host.value) observer.observe(host.value)
  draw()
})
onBeforeUnmount(() => {
  clearTooltipIntent()
  observer?.disconnect()
})
</script>

<template>
  <section class="gpm-map-card card">
    <div class="metric-tabs" role="tablist" aria-label="热力指标">
      <button v-for="item in frame?.heat_map || []" :key="item.key" type="button"
        role="tab" :aria-selected="item.key === metricKey"
        :class="{ active: item.key === metricKey }" :data-label="item.name"
        @click="$emit('metric', item.key)">
        <span>{{ item.name }}</span>
      </button>
    </div>
    <div v-if="frame?.map_config" ref="host" class="map-stage">
      <img ref="mapImage" class="map-image" :src="frame.map_config.image_url"
        alt="场景地图" @load="imageReady" />
      <canvas ref="canvas" @click="clickMap" @mousemove="moveMap" @mouseleave="leaveMap"></canvas>
      <Transition name="point-tooltip">
        <div v-if="tooltipPoint && tooltipAnchor" :key="String(tooltipPoint.id)"
          class="point-tooltip" :class="`on-${tooltipAnchor.side}`" role="tooltip"
          :style="{ left: `${tooltipAnchor.x}px`, top: `clamp(80px, ${tooltipAnchor.y}px, calc(100% - 10px))` }">
          <div class="tooltip-id">
            <span>序号</span>
            <strong>{{ String(tooltipPoint.index ?? tooltipPoint.id).padStart(2, '0') }}</strong>
          </div>
          <div class="tooltip-position">
            <span>坐标</span>
            <strong>
              <b>X</b> {{ formatCoordinateValue(tooltipPoint.position?.[0]) }}
              <b>Y</b> {{ formatCoordinateValue(tooltipPoint.position?.[1]) }}
            </strong>
          </div>
          <div class="tooltip-metric">
            <span>{{ metric?.name || metricKey }}</span>
            <div class="metric-reading">
              <strong :style="{ color: tooltipValueColor }">{{ formatValue(tooltipValue) }}</strong>
              <small class="metric-change" :class="`is-${tooltipChange.direction}`"
                :title="frame?.previous_batch ? '较上一次批次' : '没有可对比的上一批次'">
                {{ tooltipChange.label }}
              </small>
            </div>
          </div>
        </div>
      </Transition>
    </div>
    <div v-else class="map-empty">
      当前场景尚未配置地图，请先上传地图图片与坐标范围
    </div>
    <div v-if="frame?.map_config" class="map-legend">
      <template v-if="activeScale?.mode === 'configured'">
        <button v-for="(band, index) in scaleBands" :key="`${band.minimum}-${band.maximum}`"
          type="button" class="band-legend"
          :class="{ 'is-hidden': hiddenBandIndexes.has(index), 'is-hovered': hoveredBandIndex === index }"
          :aria-pressed="!hiddenBandIndexes.has(index)"
          :aria-label="`${formatConfiguredBandRange(band)}，点击${hiddenBandIndexes.has(index) ? '显示' : '隐藏'}该区间点位`"
          @mouseenter="setHoveredBand(index)" @mouseleave="setHoveredBand(null)"
          @focus="setHoveredBand(index)" @blur="setHoveredBand(null)"
          @click="toggleBand(index)">
          <i :style="{ background: band.color }"></i>
          <small>{{ formatConfiguredBandRange(band) }}</small>
        </button>
        <em :title="activeScale.source?.scale_set_name || ''">
          {{ activeScale.source?.scale_name || '固定标尺' }}
        </em>
      </template>
      <span v-else class="linear-legend">
        <i :style="{ background: LINEAR_HEAT_GRADIENT }"></i>
        <small>动态范围</small>
      </span>
    </div>
  </section>
</template>

<style scoped>
.gpm-map-card { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.metric-tabs {
  height: 43px; flex: 0 0 43px; display: flex; align-items: center;
  padding: 7px 10px; gap: 6px;
  overflow-x: auto; border-bottom: 1px solid var(--color-border-1);
}
.metric-tabs button {
  flex: 0 0 auto; min-height: 28px; border: 1px solid var(--color-border-1);
  border-radius: 4px; padding: 0 11px; display: grid; align-items: center;
  background: color-mix(in srgb, var(--color-fill-1) 82%, transparent);
  color: var(--color-text-3); cursor: pointer; font: inherit; white-space: nowrap;
  transition: color .14s ease, background-color .14s ease, border-color .14s ease;
}
.metric-tabs button::before,
.metric-tabs button > span { grid-area: 1 / 1; }
.metric-tabs button::before {
  content: attr(data-label); visibility: hidden; font-weight: 600;
}
.metric-tabs button:hover {
  color: var(--color-text-1); background: var(--color-fill-2); border-color: var(--color-border-3);
}
.metric-tabs button:focus-visible {
  outline: 2px solid rgba(var(--arcoblue-5), .72); outline-offset: 1px;
}
.metric-tabs button.active {
  color: rgb(var(--arcoblue-6));
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 13%, var(--color-fill-2));
  border-color: rgba(var(--arcoblue-5), .58);
  box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .06);
}
.metric-tabs button.active > span { font-weight: 600; }
.map-stage { position: relative; flex: 1; min-height: 390px; overflow: hidden; background: var(--color-bg-2); }
.map-stage img { position: absolute; inset: 0; width: 100%; height: 100%; user-select: none; pointer-events: none; }
.map-image { object-fit: contain; }
.map-stage canvas { position: absolute; inset: 0; cursor: default; }
.point-tooltip {
  position: absolute; z-index: 2; min-width: 184px; padding: 8px 10px;
  pointer-events: none; border: 1px solid rgba(255, 255, 255, .16); border-radius: 4px;
  color: rgba(255, 255, 255, .92); background: rgba(12, 16, 22, .68);
  box-shadow: 0 5px 16px rgba(0, 0, 0, .3); backdrop-filter: blur(6px);
  will-change: opacity, transform;
}
.point-tooltip.on-right {
  transform: translate(15px, calc(-100% - 10px)); transform-origin: left bottom;
}
.point-tooltip.on-left {
  transform: translate(calc(-100% - 15px), calc(-100% - 10px)); transform-origin: right bottom;
}
.point-tooltip-enter-active,
.point-tooltip-leave-active {
  transition: opacity .12s ease-out, transform .14s cubic-bezier(.2, .75, .35, 1);
}
.point-tooltip-enter-from,
.point-tooltip-leave-to { opacity: 0; }
.point-tooltip-enter-from.on-right,
.point-tooltip-leave-to.on-right {
  transform: translate(15px, calc(-100% - 5px)) scale(.985);
}
.point-tooltip-enter-from.on-left,
.point-tooltip-leave-to.on-left {
  transform: translate(calc(-100% - 15px), calc(-100% - 5px)) scale(.985);
}
.point-tooltip > div { display: flex; align-items: baseline; justify-content: space-between; gap: 18px; }
.point-tooltip > div + div { margin-top: 5px; }
.point-tooltip span { color: rgba(255, 255, 255, .58); font-size: 11px; white-space: nowrap; }
.point-tooltip strong { color: rgba(255, 255, 255, .94); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tooltip-id strong { color: rgb(var(--arcoblue-5)); }
.tooltip-position strong { display: inline-flex; gap: 5px; }
.tooltip-position b { color: rgba(255, 255, 255, .5); font: inherit; font-weight: 500; }
.metric-reading { display: inline-flex; align-items: baseline; justify-content: flex-end; }
.metric-change {
  margin-left: 7px; padding-left: 7px; border-left: 1px solid rgba(255, 255, 255, .18);
  font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.metric-change.is-up { color: rgb(var(--red-6)); }
.metric-change.is-down { color: rgb(var(--green-6)); }
.metric-change.is-flat { color: rgba(255, 255, 255, .72); }
.metric-change.is-unavailable { color: rgba(255, 255, 255, .42); }
.map-empty { flex: 1; min-height: 390px; display: grid; place-items: center; color: var(--color-text-3); }
.map-legend {
  min-height: 42px; padding: 8px 14px; display: flex; align-items: center; flex-wrap: wrap;
  gap: 10px 18px; color: var(--color-text-3); border-top: 1px solid var(--color-border-1);
}
.map-legend span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.band-legend {
  position: relative; display: inline-flex; align-items: center; gap: 6px; min-height: 24px;
  margin: -3px -5px; padding: 3px 5px; border: 1px solid transparent; border-radius: 4px;
  color: inherit; background: transparent; cursor: pointer; font: inherit; white-space: nowrap;
  transition: background-color .14s ease, border-color .14s ease, opacity .14s ease;
}
.band-legend:hover,
.band-legend.is-hovered {
  border-color: var(--color-border-2); background: color-mix(in srgb, var(--color-fill-2) 72%, transparent);
}
.band-legend:focus-visible {
  outline: 2px solid rgba(var(--arcoblue-5), .72); outline-offset: 1px;
}
.band-legend.is-hidden { opacity: .42; }
.band-legend.is-hidden i::after {
  content: ''; position: absolute; inset: 4px -2px; border-top: 1px solid var(--color-text-2);
  transform: rotate(-45deg); transform-origin: center;
}
.map-legend i { width: 10px; height: 10px; border-radius: 1px; box-shadow: 0 0 0 1px rgba(255,255,255,.16); }
.band-legend i { position: relative; }
.map-legend .linear-legend i { width: 132px; height: 8px; }
.map-legend small { color: var(--color-text-4); font-size: 11px; }
.map-legend em {
  margin-left: auto; overflow: hidden; color: var(--color-text-4); font-size: 10px;
  font-style: normal; text-overflow: ellipsis; white-space: nowrap;
}
@media (prefers-reduced-motion: reduce) {
  .metric-tabs button,
  .band-legend,
  .point-tooltip-enter-active,
  .point-tooltip-leave-active { transition: none; }
}
</style>
