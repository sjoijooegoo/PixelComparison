<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useStore } from '../store'

const store = useStore()
const cols = computed(() => store.grid.batches)
const rows = computed(() => store.grid.rows)

const FIRST_COL = 180         // 首列(检查点名)固定宽
const VISIBLE = 7             // 每页横向展示的批次列数
const COLLAPSED_W = 18        // 折叠后列宽(细条)
const panel = ref(null)
const colW = ref(160)         // 单个批次列宽(随容器自适应)
const imgH = computed(() => Math.round(colW.value * 9 / 16))   // 16:9 等比

// 临时折叠的批次列(切场景/改筛选后重置)
const collapsed = reactive(new Set())
const isCollapsed = (id) => collapsed.has(id)
function toggle(id) { collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id) }

// 受控预览:点击缩略图时,用「本行」的图片列表打开 Arco 灯箱
//(缩略图用原生 img 渲染,避免上千个重组件;放大体验不变)
const previewVisible = ref(false)
const previewList = ref([])
const previewMeta = ref([])      // 与 previewList 对齐:每张图所属批次信息
const previewCurrent = ref(0)
function openPreview(row, colIndex) {
  const list = []
  const meta = []
  let cur = 0
  row.cells.forEach((url, i) => {
    if (!url) return
    if (i === colIndex) cur = list.length
    list.push(url)
    const b = cols.value[i]
    meta.push({
      scene_name: row.scene_name,
      created_at: b.created_at,
      id: b.id,
      quality: b.shading_quality_label,
    })
  })
  previewList.value = list
  previewMeta.value = meta
  previewCurrent.value = cur
  previewVisible.value = true
}

// 基线/对比批次选择(复用 store,与列表视图同一套状态)
function roleOf(id) {
  if (store.currentBatch?.id === id) return 'current'
  if (store.baselineBatch?.id === id) return 'baseline'
  return null
}

// 按面板宽度算列宽:始终用 7 等分,使一屏正好放下 7 个批次列
function recalc() {
  const el = panel.value
  if (!el) return
  const avail = el.clientWidth - 24 - FIRST_COL - 8
  colW.value = Math.max(120, Math.floor(avail / VISIBLE))
}
let ro
onMounted(() => {
  ro = new ResizeObserver(recalc)
  if (panel.value) ro.observe(panel.value)
  recalc()
})
onUnmounted(() => ro?.disconnect())
watch(cols, () => { collapsed.clear(); recalc() })

const gridStyle = computed(() => ({
  gridTemplateColumns: `${FIRST_COL}px ` +
    cols.value.map((b) => (isCollapsed(b.id) ? COLLAPSED_W : colW.value) + 'px').join(' '),
}))
</script>

<template>
  <div class="grid-panel" ref="panel">
    <a-empty v-if="!store.filters.scene_id" description="请先在上方筛选条选择一个场景" style="margin-top: 60px" />
    <a-empty v-else-if="!cols.length" description="该场景下暂无批次" style="margin-top: 60px" />
    <div v-else class="grid-scroll">
      <div class="matrix" :style="gridStyle">
        <!-- 表头行:左上角 + 每个批次 -->
        <div class="cell head corner">检查点 \ 批次</div>
        <div v-for="b in cols" :key="b.id" class="cell head" :class="{ collapsed: isCollapsed(b.id) }">
          <button v-if="isCollapsed(b.id)" class="expand" :title="'展开 #' + b.id" @click="toggle(b.id)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
              stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
          </button>
          <template v-else>
            <button class="collapse-btn" title="折叠此列" @click="toggle(b.id)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14" /></svg>
            </button>
            <div class="bhead">
              <div class="dateline">
                <span class="date">{{ b.created_at.split(' ')[0] }}</span>
                <span class="dtime">{{ b.created_at.split(' ')[1] }}</span>
              </div>
              <div class="bsub"><span class="mono">#{{ b.id }}</span> · {{ b.shading_quality_label }}</div>
              <div class="roles">
                <button class="role-btn base" :class="{ on: roleOf(b.id) === 'baseline' }"
                  @click="store.setRole(b, 'baseline')">基线</button>
                <button class="role-btn cur" :class="{ on: roleOf(b.id) === 'current' }"
                  @click="store.setRole(b, 'current')">对比</button>
              </div>
            </div>
          </template>
        </div>

        <!-- 数据行:首列检查点名 + 各批次缩略图(原生 img,轻量) -->
        <template v-for="r in rows" :key="r.scene_name">
          <div class="cell rowhead" :title="r.scene_name" :style="{ height: imgH + 'px' }">{{ r.scene_name }}</div>
          <div v-for="(url, i) in r.cells" :key="cols[i].id" class="cell imgcell"
            :class="{ collapsed: isCollapsed(cols[i].id) }">
            <template v-if="!isCollapsed(cols[i].id)">
              <img v-if="url" class="thumb" :src="url" :alt="r.scene_name"
                loading="lazy" decoding="async" :style="{ height: imgH + 'px' }"
                @click="openPreview(r, i)" />
              <div v-else class="missing" :style="{ height: imgH + 'px' }">—</div>
            </template>
          </div>
        </template>
      </div>
      <!-- 放大后 < > 只在本行(同一检查点跨各批次)翻看 -->
      <a-image-preview-group :src-list="previewList" v-model:current="previewCurrent"
        v-model:visible="previewVisible" infinite />
    </div>

    <!-- 放大时顶部显示当前图所属批次信息(叠在灯箱之上) -->
    <teleport to="body">
      <div v-if="previewVisible && previewMeta[previewCurrent]" class="preview-banner">
        <span class="pb-date">{{ previewMeta[previewCurrent].created_at }}</span>
        <span class="pb-dot">·</span>
        <span class="mono">批次 #{{ previewMeta[previewCurrent].id }}</span>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.grid-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0 12px 12px; }
.grid-scroll { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--color-border-2); border-radius: 8px; }
.matrix { display: grid; width: max-content; transition: grid-template-columns .26s ease; }

.cell {
  border-right: 1px solid var(--color-border-2);
  border-bottom: 1px solid var(--color-border-2);
  box-sizing: border-box;
}

/* 表头:吸顶(固定高度,折叠/展开不抖动) */
.head {
  position: sticky; top: 0; z-index: 3;
  height: 84px; box-sizing: border-box;
  display: flex; flex-direction: column; justify-content: center;
  background: var(--color-bg-3); padding: 4px 8px;
}
/* 首列:吸左 */
.rowhead {
  position: sticky; left: 0; z-index: 2;
  background: var(--color-bg-2); padding: 8px 10px;
  display: flex; align-items: center;
  font-size: 12px; color: var(--color-text-2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* 左上角:吸顶吸左,层级最高 */
.corner {
  position: sticky; top: 0; left: 0; z-index: 4;
  height: 84px; box-sizing: border-box;
  display: flex; align-items: center;
  background: var(--color-bg-3); padding: 6px 8px;
  font-size: 11px; color: var(--color-text-3);
}

/* 折叠/展开按钮 */
.collapse-btn {
  position: absolute; top: 3px; right: 4px;
  display: flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 4px;
  border: none; background: none; cursor: pointer; padding: 0;
  color: var(--color-text-3); transition: background-color .15s, color .15s;
}
.collapse-btn svg { width: 13px; height: 13px; }
.collapse-btn:hover { color: rgb(var(--arcoblue-6)); background: var(--color-fill-2); }
.expand {
  width: 100%; height: 100%; min-height: 48px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: none; cursor: pointer; padding: 0;
  color: var(--color-text-3); transition: background-color .15s, color .15s;
}
.expand svg { width: 16px; height: 16px; }
.expand:hover { color: rgb(var(--arcoblue-6)); background: var(--color-fill-2); }

.bhead { display: flex; flex-direction: column; line-height: 1.3; text-align: center; }
.dateline { display: flex; align-items: baseline; justify-content: center; gap: 6px; }
.date { font-size: 15px; font-weight: 800; color: rgb(var(--arcoblue-6)); letter-spacing: .2px; }
.dtime { font-size: 12px; font-weight: 600; color: var(--color-text-2); }
.bsub { font-size: 10px; color: var(--color-text-3); white-space: nowrap; margin-top: 2px; }
.roles { display: flex; gap: 4px; justify-content: center; margin-top: 5px; }
.role-btn {
  border: 1px solid var(--color-border-2); background: transparent; cursor: pointer;
  font-size: 10px; padding: 1px 7px; border-radius: 4px; line-height: 1.6; font-family: inherit;
}
.role-btn.base { color: rgb(var(--batch-base)); }
.role-btn.cur { color: rgb(var(--batch-cur)); }
.role-btn.base.on { background: rgb(var(--batch-base)); border-color: rgb(var(--batch-base)); color: #fff; }
.role-btn.cur.on { background: rgb(var(--batch-cur)); border-color: rgb(var(--batch-cur)); color: #fff; }

.imgcell { position: relative; z-index: 1; background: #0d1117; }
.cell.collapsed { padding: 0; overflow: hidden; background: var(--color-fill-2); }
.thumb { display: block; width: 100%; object-fit: cover; cursor: zoom-in; }
.missing { display: flex; align-items: center; justify-content: center; color: var(--color-text-4); }

/* 放大灯箱顶部的批次信息条(teleport 到 body,仍受 scoped 作用) */
.preview-banner {
  position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
  z-index: 100000; pointer-events: none;
  display: flex; align-items: center; gap: 8px;
  padding: 7px 16px; border-radius: 8px;
  background: rgba(0, 0, 0, .62); color: #fff; font-size: 13px;
}
.preview-banner .pb-scene { font-weight: 600; }
.preview-banner .pb-date { color: rgb(var(--arcoblue-5)); font-weight: 700; }
.preview-banner .pb-dot { opacity: .5; }
</style>
