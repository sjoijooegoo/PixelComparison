<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { createMapProjection, containedImageRect } from '../gpmHeatmap/mapProjection'
import { formatMetricValue, heatColor, HEAT_COLORS, metricThresholds } from '../gpmHeatmap/colors'

const props = defineProps({
  frame: { type: Object, default: null },
  metricKey: { type: String, default: 'Scene_DC' },
  selectedPointId: { type: [Number, String], default: null },
})
const emit = defineEmits(['select', 'metric'])

const host = ref(null)
const canvas = ref(null)
const mapImage = ref(null)
let observer = null
let projected = []

const metric = computed(() => props.frame?.heat_map?.find((item) => item.key === props.metricKey))
const configuredRange = computed(() => props.frame?.map_config?.color_ranges?.[props.metricKey])
const thresholds = computed(() => metricThresholds(props.frame?.points, props.metricKey, configuredRange.value))
const legend = computed(() => {
  const [a, b, c] = thresholds.value
  return [
    `< ${formatMetricValue(a)}`,
    `${formatMetricValue(a)} – ${formatMetricValue(b)}`,
    `${formatMetricValue(b)} – ${formatMetricValue(c)}`,
    `≥ ${formatMetricValue(c)}`,
  ]
})

function projectionForSize(width, height) {
  const config = props.frame?.map_config
  if (!config || !mapImage.value?.naturalWidth) return null
  const rect = containedImageRect(
    width, height, mapImage.value.naturalWidth, mapImage.value.naturalHeight,
  )
  return createMapProjection(config, rect)
}

function drawArrow(context, point, direction, color) {
  const startX = point.x + direction.x * 9
  const startY = point.y + direction.y * 9
  const endX = point.x + direction.x * 27
  const endY = point.y + direction.y * 27
  context.beginPath()
  context.moveTo(startX, startY)
  context.lineTo(endX, endY)
  context.strokeStyle = 'rgba(255,255,255,.9)'
  context.lineWidth = 1.5
  context.stroke()
  const angle = Math.atan2(direction.y, direction.x)
  context.beginPath()
  context.moveTo(endX, endY)
  context.lineTo(endX - 6 * Math.cos(angle - Math.PI / 6), endY - 6 * Math.sin(angle - Math.PI / 6))
  context.lineTo(endX - 6 * Math.cos(angle + Math.PI / 6), endY - 6 * Math.sin(angle + Math.PI / 6))
  context.closePath()
  context.fillStyle = color
  context.fill()
}

function draw() {
  const element = canvas.value
  const container = host.value
  if (!element || !container) return
  const width = container.clientWidth
  const height = container.clientHeight
  const ratio = window.devicePixelRatio || 1
  element.width = Math.max(1, Math.round(width * ratio))
  element.height = Math.max(1, Math.round(height * ratio))
  element.style.width = `${width}px`
  element.style.height = `${height}px`
  const context = element.getContext('2d')
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, width, height)
  const projection = projectionForSize(width, height)
  if (!projection) return
  projected = []
  for (const source of props.frame?.points || []) {
    const point = projection.project(source.position)
    if (!point.inBounds) continue
    const direction = projection.projectDirection(source.direction)
    const selected = Number(source.id) === Number(props.selectedPointId)
    const size = selected ? 13 : 10
    const color = heatColor(source.heat_map_data?.[props.metricKey], thresholds.value)
    context.fillStyle = color
    context.fillRect(point.x - size / 2, point.y - size / 2, size, size)
    context.strokeStyle = selected ? '#ffffff' : 'rgba(0,0,0,.72)'
    context.lineWidth = selected ? 2 : 1
    context.strokeRect(point.x - size / 2, point.y - size / 2, size, size)
    if (props.frame?.scene?.show_direction) drawArrow(context, point, direction, color)
    projected.push({ source, x: point.x, y: point.y, hit: selected ? 15 : 12 })
  }
}

function clickMap(event) {
  const rect = canvas.value.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  let nearest = null
  let distance = Infinity
  for (const point of projected) {
    const current = Math.hypot(x - point.x, y - point.y)
    if (current <= point.hit && current < distance) {
      nearest = point.source
      distance = current
    }
  }
  if (nearest) emit('select', nearest.id)
}

function imageReady() {
  nextTick(draw)
}

// frame 由 store 以不可变响应对象整体替换，无需深度遍历可能很大的点位数组。
watch(() => [props.frame, props.metricKey, props.selectedPointId], draw)
onMounted(() => {
  observer = new ResizeObserver(draw)
  observer.observe(host.value)
  draw()
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section class="gpm-map-card card">
    <div class="metric-tabs" role="tablist" aria-label="热力指标">
      <button v-for="item in frame?.heat_map || []" :key="item.key" type="button"
        :class="{ active: item.key === metricKey }" @click="$emit('metric', item.key)">
        {{ item.name }}
      </button>
    </div>
    <div v-if="frame?.map_config" ref="host" class="map-stage">
      <img ref="mapImage" class="map-image" :src="frame.map_config.image_url"
        alt="场景地图" @load="imageReady" />
      <canvas ref="canvas" @click="clickMap"></canvas>
    </div>
    <div v-else class="map-empty">
      当前场景尚未配置地图，请先上传地图图片与坐标范围
    </div>
    <div v-if="frame?.map_config" class="map-legend">
      <span class="metric-name">{{ metric?.name || metricKey }}</span>
      <span v-for="(label, index) in legend" :key="index">
        <i :style="{ background: HEAT_COLORS[index] }"></i>{{ label }}
      </span>
    </div>
  </section>
</template>

<style scoped>
.gpm-map-card { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.metric-tabs {
  height: 43px; flex: 0 0 43px; display: flex; gap: 3px; align-items: stretch;
  padding: 0 10px; overflow-x: auto; border-bottom: 1px solid var(--color-border-1);
}
.metric-tabs button {
  flex: 0 0 auto; border: 0; border-bottom: 2px solid transparent; padding: 0 12px;
  background: transparent; color: var(--color-text-3); cursor: pointer; font: inherit;
}
.metric-tabs button:hover { color: var(--color-text-1); }
.metric-tabs button.active { color: rgb(var(--arcoblue-6)); border-bottom-color: rgb(var(--arcoblue-6)); font-weight: 600; }
.map-stage { position: relative; flex: 1; min-height: 390px; overflow: hidden; background: var(--color-bg-2); }
.map-stage img { position: absolute; inset: 0; width: 100%; height: 100%; user-select: none; pointer-events: none; }
.map-image { object-fit: contain; }
.map-stage canvas { position: absolute; inset: 0; cursor: crosshair; }
.map-empty { flex: 1; min-height: 390px; display: grid; place-items: center; color: var(--color-text-3); }
.map-legend {
  min-height: 42px; padding: 8px 14px; display: flex; align-items: center; flex-wrap: wrap;
  gap: 10px 18px; color: var(--color-text-3); border-top: 1px solid var(--color-border-1);
}
.map-legend span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.map-legend i { width: 9px; height: 9px; border-radius: 1px; box-shadow: 0 0 0 1px rgba(255,255,255,.18); }
.map-legend .metric-name { color: var(--color-text-2); font-weight: 600; }
</style>
