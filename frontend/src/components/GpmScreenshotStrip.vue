<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] },
  selectedPointId: { type: [Number, String], default: null },
})
const emit = defineEmits(['select'])
const strip = ref(null)
const dragging = ref(false)
const previewVisible = ref(false)
const previewPoint = ref(null)
let mouseActive = false
let startX = 0
let startY = 0
let startScrollLeft = 0
let direction = ''
let suppressClickUntil = 0
let lastSelectionId = null
let lastSelectionAt = 0

watch(() => [props.selectedPointId, props.points.length], async () => {
  await nextTick()
  strip.value?.querySelector('.shot.active')?.scrollIntoView?.({
    behavior: 'smooth', block: 'nearest', inline: 'center',
  })
}, { immediate: true })

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
  emit('select', point.id)
}

function openPreview(point) {
  previewPoint.value = point
  previewVisible.value = true
}

function setPreviewVisible(visible) {
  previewVisible.value = visible
  if (!visible) previewPoint.value = null
}
</script>

<template>
  <section class="screenshot-card card">
    <div ref="strip" class="shot-strip" :class="{ dragging }" @mousedown="onMouseDown">
      <button v-for="point in points" :key="point.id" type="button" class="shot"
        :class="{ active: Number(point.id) === Number(selectedPointId) }"
        title="单击选择，双击查看大图" @click="selectPoint(point)"
        @dblclick.prevent="openPreview(point)">
        <img :src="point.thumbnail_url" :alt="`点位 ${point.index}`" loading="lazy"
          draggable="false" />
        <span>{{ String(point.index).padStart(2, '0') }}</span>
      </button>
    </div>
    <a-image-preview v-if="previewVisible && previewPoint"
      :src="previewPoint.image_url || previewPoint.thumbnail_url" :visible="true"
      @update:visible="setPreviewVisible" />
  </section>
</template>

<style scoped>
.screenshot-card { padding: 8px 12px 4px; overflow: visible; }
.shot-strip {
  display: flex; gap: 12px; overflow-x: auto; overflow-y: hidden; padding: 0 1px 4px;
  scroll-behavior: smooth; overscroll-behavior-inline: contain;
  cursor: default; touch-action: pan-y; user-select: none;
}
.shot-strip.dragging { cursor: grabbing; scroll-behavior: auto; }
.shot-strip.dragging * { cursor: grabbing !important; }
.shot {
  flex: 0 0 280px; padding: 0; overflow: hidden; border: 1px solid var(--color-border-1);
  border-radius: 5px; background: var(--color-fill-1); color: var(--color-text-2); cursor: pointer;
}
.shot:hover { border-color: var(--color-border-3); }
.shot.active { border-color: rgb(var(--arcoblue-6)); box-shadow: 0 0 0 1px rgb(var(--arcoblue-6)); }
.shot img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: var(--color-fill-2); }
.shot span { height: 24px; display: grid; place-items: center; font-variant-numeric: tabular-nums; }
</style>
