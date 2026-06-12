<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStore, STATUS_META } from '../store'

const store = useStore()
const detail = computed(() => store.detail)
const paired = computed(() => !!(detail.value?.current_url && detail.value?.baseline_url))

const sliderRatio = ref(0.5)
const stage = ref(null)
let dragging = false

function startDrag() { dragging = true }
function onMove(e) {
  if (!dragging || !stage.value) return
  const rect = stage.value.getBoundingClientRect()
  sliderRatio.value = Math.min(0.99, Math.max(0.01, (e.clientX - rect.left) / rect.width))
}
function stopDrag() { dragging = false }
function stageClick(e) {
  const rect = stage.value.getBoundingClientRect()
  sliderRatio.value = Math.min(0.99, Math.max(0.01, (e.clientX - rect.left) / rect.width))
}

function onKey(e) {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return
  if (e.key === 'ArrowLeft') store.gotoPrev()
  if (e.key === 'ArrowRight') store.gotoNext()
}

onMounted(() => {
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', stopDrag)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', stopDrag)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <section class="detail">
    <template v-if="detail">
      <div class="head">
        <h3>{{ detail.name }}</h3>
        <a-tag :color="STATUS_META[detail.status].color" size="small">{{ STATUS_META[detail.status].label }}</a-tag>
        <a-button-group size="mini">
          <a-button :disabled="!detail.prev_id" @click="store.gotoPrev()">‹ 上一个</a-button>
          <a-button disabled>{{ detail.index }}/{{ detail.sibling_total }}</a-button>
          <a-button :disabled="!detail.next_id" @click="store.gotoNext()">下一个 ›</a-button>
        </a-button-group>
        <a-radio-group v-model="store.viewMode" type="button" size="small" style="margin-left:auto">
          <a-radio value="tri">三视图</a-radio>
          <a-radio value="slide" :disabled="!paired">滑动对比</a-radio>
          <a-radio value="raw">原图对比</a-radio>
        </a-radio-group>
        <a-select v-model="store.zoom" size="small" style="width:86px">
          <a-option :value="50">50%</a-option>
          <a-option :value="100">100%</a-option>
          <a-option :value="150">150%</a-option>
          <a-option :value="200">200%</a-option>
        </a-select>
      </div>

      <a-alert v-if="detail.status === 'added'" type="info" style="margin-top:10px">
        新增场景:参照批次 ({{ store.selectedComparison?.ref_label }}) 中没有此场景,确认无误后可将其晋升进基线。
      </a-alert>
      <a-alert v-if="detail.status === 'missing'" type="error" style="margin-top:10px">
        场景缺失:参照批次中存在此场景,但当前批次未产出截图,请检查采集任务。
      </a-alert>

      <!-- 三视图 / 原图对比 -->
      <div v-if="store.viewMode !== 'slide' || !paired" class="views">
        <div class="card">
          <div class="cap">当前版本 ({{ store.selectedComparison?.branch }})</div>
          <div v-if="detail.current_url" class="frame">
            <img :src="detail.current_url" :style="{ width: store.zoom + '%' }" alt="当前版本">
          </div>
          <div v-else class="frame empty">当前批次无此场景</div>
          <div class="meta text-secondary">批次 #{{ store.selectedComparison?.batch_id }}</div>
        </div>
        <div class="card">
          <div class="cap">参照版本 ({{ store.selectedComparison?.ref_label }})</div>
          <div v-if="detail.baseline_url" class="frame">
            <img :src="detail.baseline_url" :style="{ width: store.zoom + '%' }" alt="参照版本">
          </div>
          <div v-else class="frame empty">参照批次中无此场景</div>
          <div class="meta text-secondary">参照批次 #{{ store.selectedComparison?.ref_batch_id }}</div>
        </div>
        <div v-if="store.viewMode === 'tri'" class="card">
          <div class="cap">差异热力图</div>
          <div v-if="detail.heatmap_url" class="frame">
            <img :src="detail.heatmap_url" :style="{ width: store.zoom + '%' }" alt="差异热力图">
          </div>
          <div v-else class="frame empty">无对比结果</div>
          <div class="meta text-secondary">低 <span class="heat-bar"></span> 高</div>
        </div>
      </div>

      <!-- 滑动对比 -->
      <div v-else class="slide-wrap">
        <div class="stage" ref="stage" @click="stageClick">
          <img :src="detail.baseline_url" draggable="false" alt="参照版本">
          <div class="top" :style="{ width: sliderRatio * 100 + '%' }">
            <img :src="detail.current_url" draggable="false" alt="当前版本">
          </div>
          <div class="handle" :style="{ left: `calc(${sliderRatio * 100}% - 1px)` }" @pointerdown.stop="startDrag"></div>
          <span class="tag" style="left:10px">当前版本</span>
          <span class="tag" style="right:10px">参照版本</span>
        </div>
        <div class="meta text-secondary">拖动分割线对比两个版本 · 960x540 · PNG</div>
      </div>
    </template>
    <a-empty v-else style="margin-top: 80px" description="请选择场景" />
  </section>
</template>

<style scoped>
.detail { flex: 1; min-width: 0; padding: 12px 16px; overflow-y: auto; }
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head h3 { margin: 0; font-size: 15px; }
.views { display: flex; gap: 12px; margin-top: 12px; align-items: flex-start; }
.card { flex: 1; min-width: 0; }
.cap { font-size: 12px; color: var(--color-text-2); margin-bottom: 6px; }
.frame { background: #0d1117; border-radius: 6px; overflow: auto; }
.frame img { display: block; min-width: 100%; }
.frame.empty {
  aspect-ratio: 16/9; display: flex; align-items: center; justify-content: center;
  color: var(--color-text-3); background: var(--color-fill-2); font-size: 12px;
}
.meta { display: flex; align-items: center; gap: 6px; padding: 5px 2px; font-size: 12px; }
.heat-bar {
  display: inline-block; width: 90px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg,#1b1bb3,#00b3ff,#00d26a,#ffe000,#ff6a00,#e00000);
}
.slide-wrap { margin-top: 12px; max-width: 960px; }
.stage { position: relative; border-radius: 6px; overflow: hidden; user-select: none; background: #0d1117; }
.stage > img { display: block; width: 100%; }
.top { position: absolute; inset: 0 auto 0 0; overflow: hidden; }
.top img { display: block; height: 100%; max-width: none; }
.handle {
  position: absolute; top: 0; bottom: 0; width: 2px; background: #fff; cursor: ew-resize;
  box-shadow: 0 0 4px rgba(0,0,0,.6);
}
.handle::after {
  content: "◀ ▶"; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
  background: #fff; color: #1d2129; font-size: 9px; padding: 5px 7px; border-radius: 12px;
  white-space: nowrap; box-shadow: 0 1px 4px rgba(0,0,0,.3);
}
.tag {
  position: absolute; top: 10px; padding: 2px 8px; border-radius: 4px;
  background: rgba(0,0,0,.55); color: #fff; font-size: 12px;
}
</style>
