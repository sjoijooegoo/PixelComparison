<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStore } from '../store'

const store = useStore()
const detail = computed(() => store.orientedDetail)   // 按当前换向(flip)取向
const paired = computed(() => !!(detail.value?.current_url && detail.value?.baseline_url))

// 相机位姿(新版上报带):location(x,y,z) + rotation(pitch,yaw,roll)
const n1 = (v) => {
  if (typeof v !== 'number') return v
  const s = v.toFixed(1)
  return s === '-0.0' ? '0.0' : s   // 规避负零显示
}
const camera = computed(() => {
  const c = detail.value?.camera
  if (!c?.location || !c?.rotation) return null
  const { x, y, z } = c.location
  const { pitch, yaw, roll } = c.rotation
  return {
    loc: `${n1(x)}, ${n1(y)}, ${n1(z)}`,
    rot: `${n1(pitch)}, ${n1(yaw)}, ${n1(roll)}`,
  }
})

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
        <div class="title-wrap">
          <h3>{{ detail.name }}</h3>
          <span v-if="camera" class="cam-inline text-secondary">
            位置 ({{ camera.loc }}) <span class="cam-dot">·</span> 旋转 ({{ camera.rot }})
          </span>
        </div>
        <a-tag v-if="detail.status === 'added'" color="arcoblue" size="small">新增检查点</a-tag>
        <a-tag v-else-if="detail.status === 'missing'" color="gray" size="small">检查点缺失</a-tag>
        <a-radio-group v-model="store.viewMode" type="button" size="small" style="margin-left:auto">
          <a-radio value="tri">差异热力图</a-radio>
          <a-radio value="slide" :disabled="!paired">滑动对比</a-radio>
        </a-radio-group>
      </div>

      <a-alert v-if="detail.status === 'added'" type="info" style="margin-top:10px">
        新增检查点:基线批次 ({{ store.orientedComparison?.ref_label }}) 中没有此检查点,确认无误后可将其晋升进基线。
      </a-alert>
      <a-alert v-if="detail.status === 'missing'" type="error" style="margin-top:10px">
        检查点缺失:基线批次中存在此检查点,但对比批次未产出截图,请检查采集任务。
      </a-alert>

      <!-- 差异热力图模式:上排 当前/参照(小) + 下排 热力图(大),三图均可点击看大图 -->
      <a-image-preview-group v-if="store.viewMode !== 'slide' || !paired" infinite class="tri-wrap">
        <div class="views-top">
          <div class="view-col">
            <div class="cap"><i class="cap-dot dot-ref"></i>基线版本</div>
            <div v-if="detail.baseline_url" class="frame compact">
              <a-image :src="detail.baseline_url" alt="基线版本" width="100%" />
            </div>
            <div v-else class="frame compact empty">基线批次中无此检查点</div>
          </div>
          <div class="view-col">
            <div class="cap"><i class="cap-dot dot-cur"></i>对比版本</div>
            <div v-if="detail.current_url" class="frame compact">
              <a-image :src="detail.current_url" alt="对比版本" width="100%" />
            </div>
            <div v-else class="frame compact empty">对比批次无此检查点</div>
          </div>
        </div>

        <div v-if="store.viewMode === 'tri'" class="heat-row">
          <div class="cap"><i class="cap-dot dot-heat"></i>差异热力图</div>
          <div v-if="detail.heatmap_url" class="frame heat">
            <a-image :src="detail.heatmap_url" alt="差异热力图" width="100%" />
          </div>
          <div v-else class="frame heat empty">无对比结果</div>
          <div class="meta text-secondary">低 <span class="heat-bar"></span> 高</div>
        </div>
      </a-image-preview-group>

      <!-- 滑动对比 -->
      <div v-else class="slide-wrap">
        <div class="stage" ref="stage" @click="stageClick">
          <img :src="detail.current_url" draggable="false" alt="对比版本">
          <div class="top" :style="{ width: sliderRatio * 100 + '%' }">
            <img :src="detail.baseline_url" draggable="false" alt="基线版本">
          </div>
          <div class="handle" :style="{ left: `calc(${sliderRatio * 100}% - 1px)` }" @pointerdown.stop="startDrag"></div>
          <span class="tag" style="left:10px">基线版本</span>
          <span class="tag" style="right:10px">对比版本</span>
        </div>
        <div class="meta text-secondary">拖动分割线对比两个版本<template v-if="store.orientedComparison?.resolution"> · {{ store.orientedComparison.resolution }}</template> · PNG</div>
      </div>

      <!-- 检查点切换:浮动在右下角 -->
      <div class="scene-nav">
        <a-button-group size="small">
          <a-button :disabled="!detail.prev_id" @click="store.gotoPrev()">‹ 上一个</a-button>
          <a-button disabled>{{ detail.index }}/{{ detail.sibling_total }}</a-button>
          <a-button :disabled="!detail.next_id" @click="store.gotoNext()">下一个 ›</a-button>
        </a-button-group>
      </div>
    </template>
    <a-empty v-else style="margin-top: 80px" description="请选择检查点" />
  </section>
</template>

<style scoped>
/* 详情区纵向填充,内容尽量一屏显示,不滚动 */
.detail { flex: 1; min-width: 0; padding: 12px 16px; overflow: hidden; display: flex; flex-direction: column; position: relative; }
/* 检查点切换:浮动右下角 */
.scene-nav {
  position: absolute; right: 18px; bottom: 14px; z-index: 5;
  border-radius: 8px; box-shadow: 0 2px 10px rgba(0, 0, 0, .3);
  background: var(--color-bg-2);
}
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex: 0 0 auto; margin-bottom: 15px; }
.head h3 { margin: 0; font-size: 17px; font-weight: 600; }
/* 相机位姿:与检查点名同一行的小字 */
/* 名称 + 位置:位置像下标一样贴在名称右下角 */
.title-wrap { display: flex; align-items: flex-end; gap: 6px; min-width: 0; }
.cam-inline { font-size: 11px; white-space: nowrap; padding-bottom: 2px; }
.cam-inline .cam-dot { color: var(--color-text-4); }
/* 热力图模式容器:纵向填满剩余高度 */
.tri-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; }
/* 上排:基线 / 对比,两图按高度等比 16:9(无黑边),并排靠左 */
.views-top { display: flex; gap: 8px; flex: 0 0 auto; justify-content: flex-start; align-items: flex-start; }
.view-col { flex: 0 0 auto; min-width: 0; }
/* 下排:差异热力图,占满剩余高度,按高度等比(无黑边),左对齐 */
.heat-row { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: flex-start; margin-top: 20px; }
.cap { font-size: 12px; color: var(--color-text-2); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.cap-dot { width: 8px; height: 8px; border-radius: 2px; flex: 0 0 8px; }
.dot-cur { background: rgb(var(--batch-cur)); }
.dot-ref { background: rgb(var(--batch-base)); }
.dot-heat { background: linear-gradient(135deg, #00b3ff, #ffe000, #e00000); }
.frame {
  background: #0d1117; border-radius: 8px; overflow: hidden;
  border: 1px solid var(--color-border-2);
}
.frame :deep(.arco-image) { display: block; width: 100%; height: 100%; cursor: zoom-in; }
.frame :deep(.arco-image-img) { display: block; width: 100%; height: 100%; object-fit: contain; }
/* 上排小图:按高度等比 16:9(框=图片大小,零黑边) */
.frame.compact { height: 24vh; aspect-ratio: 16 / 9; width: auto; max-width: 100%; }
/* 下排热力图:占满剩余高度,按高度等比(零黑边) */
.frame.heat { flex: 1; min-height: 0; aspect-ratio: 16 / 9; width: auto; max-width: 100%; }
.frame.empty {
  display: flex; align-items: center; justify-content: center;
  color: var(--color-text-3); background: var(--color-fill-2); font-size: 12px;
}
.frame.compact.empty { aspect-ratio: 16/9; }
.meta { display: flex; align-items: center; gap: 6px; padding: 5px 2px; font-size: 12px; }
.heat-bar {
  display: inline-block; width: 90px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg,#1b1bb3,#00b3ff,#00d26a,#ffe000,#ff6a00,#e00000);
}
.slide-wrap { margin: 12px auto 0; width: 100%; }
.slide-wrap .meta { justify-content: center; }
/* 自适应:占满可用宽度,同时受窗口高度约束,保持 16:9 */
.stage {
  position: relative; border-radius: 6px; overflow: hidden; user-select: none; background: #0d1117;
  width: min(100%, (100vh - 230px) * 16 / 9);
  margin: 0 auto;
}
.stage > img { display: block; width: 100%; }
.top { position: absolute; inset: 0 auto 0 0; overflow: hidden; }
.top img { display: block; height: 100%; max-width: none; }
.handle {
  position: absolute; top: 0; bottom: 0; width: 2px; background: #fff; cursor: ew-resize;
  box-shadow: 0 0 4px rgba(0,0,0,.6);
}
.handle::after {
  content: ""; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
  width: 28px; height: 28px; border-radius: 50%; box-shadow: 0 1px 6px rgba(0,0,0,.35);
  background: #fff url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14"><path d="M5.2 3.8 2 7l3.2 3.2M8.8 3.8 12 7l-3.2 3.2" fill="none" stroke="%234e5969" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>') center no-repeat;
}
.tag {
  position: absolute; top: 10px; padding: 2px 8px; border-radius: 4px;
  background: rgba(0,0,0,.55); color: #fff; font-size: 12px;
}
</style>
