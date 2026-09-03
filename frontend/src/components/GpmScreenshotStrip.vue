<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] },
  selectedPointId: { type: [Number, String], default: null },
})
const emit = defineEmits(['select'])
const strip = ref(null)
const dragging = ref(false)
const previewVisible = ref(false)
const previewCurrent = ref(0)
const previewUrls = computed(() => props.points.map(
  (point) => point.image_url || point.thumbnail_url,
))
const shotElements = new Map()
let mouseActive = false
let startX = 0
let startY = 0
let startScrollLeft = 0
let direction = ''
let suppressClickUntil = 0
let lastSelectionId = null
let lastSelectionAt = 0
let localSelectionKey = null

function pointKey(value) {
  return value == null ? '' : String(value)
}

function setShotElement(pointId, element) {
  const key = pointKey(pointId)
  if (element) shotElements.set(key, element)
  else shotElements.delete(key)
}

function revealPoint(pointId) {
  const container = strip.value
  const shot = shotElements.get(pointKey(pointId))
  if (!container || !shot) return
  const shotLeft = shot.offsetLeft
  const shotRight = shotLeft + shot.offsetWidth
  const visibleLeft = container.scrollLeft
  const visibleRight = visibleLeft + container.clientWidth
  if (shotLeft >= visibleLeft && shotRight <= visibleRight) return
  container.scrollLeft = Math.max(
    0,
    shotLeft - (container.clientWidth - shot.offsetWidth) / 2,
  )
}

defineExpose({ revealPoint })

watch(
  [() => props.selectedPointId, () => props.points],
  async ([pointId], previousValues) => {
    const key = pointKey(pointId)
    const previousKey = pointKey(previousValues?.[0])
    if (key !== previousKey && key && key === localSelectionKey) {
      localSelectionKey = null
      return
    }
    localSelectionKey = null
    if (!key) return
    await nextTick()
    revealPoint(pointId)
  },
  { flush: 'post', immediate: true },
)

function onMouseDown(event) {
  if (event.button !== 0 || previewVisible.value || !strip.value) return
  event.preventDefault()
  mouseActive = true
  startX = event.clientX
  startY = event.clientY
  startScrollLeft = strip.value.scrollLeft
  direction = ''
  window.addEventListener('mousemove', onMouseMove, true)
  window.addEventListener('mouseup', endMouse, true)
}

function onMouseMove(event) {
  if (!mouseActive || !strip.value) return
  const deltaX = event.clientX - startX
  const deltaY = event.clientY - startY
  if (!direction && Math.max(Math.abs(deltaX), Math.abs(deltaY)) > 5) {
    direction = Math.abs(deltaX) >= Math.abs(deltaY) ? 'horizontal' : 'vertical'
    dragging.value = direction === 'horizontal'
  }
  if (direction !== 'horizontal') return
  event.preventDefault()
  strip.value.scrollLeft = startScrollLeft - deltaX
}

function endMouse() {
  window.removeEventListener('mousemove', onMouseMove, true)
  window.removeEventListener('mouseup', endMouse, true)
  if (!mouseActive) return
  if (direction === 'horizontal') suppressClickUntil = Date.now() + 250
  mouseActive = false
  direction = ''
  dragging.value = false
}

onUnmounted(endMouse)

function selectPoint(point) {
  const now = Date.now()
  if (now < suppressClickUntil) return
  if (Number(point.id) === Number(lastSelectionId) && now - lastSelectionAt < 300) return
  lastSelectionId = point.id
  lastSelectionAt = now
  localSelectionKey = pointKey(point.id)
  emit('select', point.id)
}

function openPreview(point) {
  const index = props.points.findIndex((item) => pointKey(item.id) === pointKey(point.id))
  previewCurrent.value = index >= 0 ? index : 0
  previewVisible.value = true
}

function setPreviewVisible(visible) {
  previewVisible.value = visible
}
</script>

<template>
  <section class="screenshot-card card">
    <div ref="strip" class="shot-strip" :class="{ dragging }" @mousedown="onMouseDown">
      <button v-for="point in points" :key="point.id"
        :ref="(element) => setShotElement(point.id, element)" type="button" class="shot"
        :class="{ active: Number(point.id) === Number(selectedPointId) }"
        :aria-label="`点位 ${point.index}，单击选择，双击查看大图`" @click="selectPoint(point)"
        @dblclick.prevent="openPreview(point)">
        <img :src="point.thumbnail_url" :alt="`点位 ${point.index}`" loading="lazy"
          draggable="false" />
        <span>{{ String(point.index).padStart(2, '0') }}</span>
      </button>
    </div>
    <a-image-preview-group v-if="points.length" :src-list="previewUrls" :infinite="false"
      v-model:current="previewCurrent" :visible="previewVisible"
      @update:visible="setPreviewVisible" />
  </section>
</template>

<style scoped>
.screenshot-card { padding: 8px 12px 4px; overflow: visible; }
.shot-strip {
  display: flex; gap: 12px; overflow-x: auto; overflow-y: hidden; padding: 0 1px 4px;
  scroll-behavior: auto; overscroll-behavior-inline: contain;
  cursor: pointer; touch-action: pan-y; user-select: none;
}
.shot-strip.dragging { cursor: grabbing; }
.shot-strip.dragging * { cursor: grabbing !important; }
.shot {
  flex: 0 0 300px; padding: 0; overflow: hidden; border: 1px solid var(--color-border-1);
  border-radius: 5px; background: var(--color-fill-1); color: var(--color-text-2); cursor: pointer;
  content-visibility: auto; contain-intrinsic-size: 300px 194px;
}
.shot:hover { border-color: var(--color-border-3); }
.shot.active { border-color: rgb(var(--arcoblue-6)); box-shadow: 0 0 0 1px rgb(var(--arcoblue-6)); }
.shot img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: var(--color-fill-2); }
.shot span { height: 24px; display: grid; place-items: center; font-variant-numeric: tabular-nums; }
</style>
