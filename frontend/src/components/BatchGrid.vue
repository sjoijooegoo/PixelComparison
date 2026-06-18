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
            </div>
          </template>
        </div>

        <!-- 每行一个预览组:放大后 < > 只在本行(同一检查点跨批次)翻看 -->
        <template v-for="r in rows" :key="r.scene_name">
          <div class="cell rowhead" :title="r.scene_name">{{ r.scene_name }}</div>
          <a-image-preview-group infinite class="row-group">
            <div v-for="(url, i) in r.cells" :key="cols[i].id" class="cell imgcell"
              :class="{ collapsed: isCollapsed(cols[i].id) }">
              <template v-if="!isCollapsed(cols[i].id)">
                <a-image v-if="url" :src="url" :alt="r.scene_name" loading="lazy"
                  width="100%" :height="imgH" fit="cover" show-loader />
                <div v-else class="missing" :style="{ height: imgH + 'px' }">—</div>
              </template>
            </div>
          </a-image-preview-group>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0 12px 12px; }
.grid-scroll { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--color-border-2); border-radius: 8px; }
.matrix { display: grid; width: max-content; transition: grid-template-columns .26s ease; }
/* 每行预览组不参与布局,组内单元格直接落到 grid 上 */
.row-group { display: contents; }

.cell {
  border-right: 1px solid var(--color-border-2);
  border-bottom: 1px solid var(--color-border-2);
  box-sizing: border-box;
}

/* 表头:吸顶(固定高度,折叠/展开不抖动) */
.head {
  position: sticky; top: 0; z-index: 3;
  height: 56px; box-sizing: border-box;
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
  height: 56px; box-sizing: border-box;
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

.imgcell { position: relative; z-index: 1; background: #0d1117; }
.cell.collapsed { padding: 0; overflow: hidden; background: var(--color-fill-2); }
.imgcell :deep(.arco-image) { display: block; width: 100%; }
.imgcell :deep(.arco-image-img) { cursor: zoom-in; }
.missing { display: flex; align-items: center; justify-content: center; color: var(--color-text-4); }
</style>
