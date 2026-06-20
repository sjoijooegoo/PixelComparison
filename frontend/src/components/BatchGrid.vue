<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useStore, p4Label } from '../store'

const store = useStore()
const cols = computed(() => store.grid.batches)
const rows = computed(() => store.grid.rows)

const FIRST_COL = 140         // 首列(检查点名)固定宽
const VISIBLE = 8             // 全屏时横向展示的批次列数(据此标定列宽)
const COLLAPSED_W = 18        // 折叠后列宽(细条)
const MIN_COL = 120           // 列宽下限
const MAX_COL = 300           // 列宽上限
const panel = ref(null)
const colW = ref(160)         // 单个批次列宽(按全屏标定,固定;窗口拉伸不变)
const imgH = computed(() => Math.round(colW.value * 9 / 16))   // 16:9 等比

// 最右「差异热力图」列(吸附):展示已选基线/对比这对批次各检查点的差异热力图。
// 只读命中缓存(store.gridHeatmaps),未对比过则该列留空 + 表头提示,绝不触发计算。
const baselineBatch = computed(() => store.baselineBatch)
const currentBatch = computed(() => store.currentBatch)
const bothSelected = computed(() =>
  !!(currentBatch.value && baselineBatch.value && currentBatch.value.id !== baselineBatch.value.id))
// gridHeatmaps 是否正属于当前这对批次(异步返回期间避免错位)
const heatForPair = computed(() => {
  const h = store.gridHeatmaps
  return h && h.current_id === currentBatch.value?.id && h.baseline_id === baselineBatch.value?.id ? h : null
})
const heatExists = computed(() => !!heatForPair.value?.exists)
const heatNoCache = computed(() => heatForPair.value?.exists === false)
const heatUrl = (sceneName) => (heatExists.value ? heatForPair.value.map[sceneName] || '' : '')

// 热力图单图放大(独立于矩阵方向键导航)
const heatmapVisible = ref(false)
const heatmapSrc = ref('')
function openHeatmap(url) {
  if (!url) return
  heatmapSrc.value = url
  heatmapVisible.value = true
}
// 刚算完的热力图文件可能有极短的落盘/服务竞态导致首次 404,失败后带缓存戳重试几次
function onHeatErr(e) {
  const img = e.target
  const n = Number(img.dataset.retry || 0)
  if (n >= 3) return
  img.dataset.retry = n + 1
  const base = img.src.split('?')[0]
  setTimeout(() => { img.src = `${base}?r=${Date.now()}` }, 300 * (n + 1))
}

// 折叠的批次列(放在 store,按批次 id;跨刷新/改筛选/切场景保留)
const isCollapsed = (id) => store.gridCollapsed.has(id)
function toggle(id) {
  const s = store.gridCollapsed
  s.has(id) ? s.delete(id) : s.add(id)
}

// 受控预览:点击缩略图后在整个矩阵里用方向键二维翻看
//(缩略图用原生 img 渲染,避免上千个重组件;放大体验不变)
//   ← →  同一检查点的不同批次(跨列)   ↑ ↓  同一批次的不同检查点(跨行)
//   到边界不循环。跳过空格(无图)与已折叠的列。
const previewVisible = ref(false)
const pr = ref(0)   // 当前行(检查点)下标
const pc = ref(0)   // 当前列(批次)下标

const previewSrc = computed(() => rows.value[pr.value]?.cells[pc.value] || '')
const previewMeta = computed(() => {
  const row = rows.value[pr.value]
  const b = cols.value[pc.value]
  if (!row || !b) return null
  return { scene_name: row.scene_name, created_at: b.created_at, id: b.id, p4_version: b.p4_version }
})

// 该格是否可作为导航落点:有图、列未折叠
function cellOk(r, c) {
  const row = rows.value[r]
  if (!row || !row.cells[c]) return false
  const b = cols.value[c]
  return !!b && !isCollapsed(b.id)
}

function openPreview(rowIndex, colIndex) {
  pr.value = rowIndex
  pc.value = colIndex
  previewVisible.value = true
}

// 朝某方向找下一个可落点;找不到就停在原地(不循环)
function step(dRow, dCol) {
  if (dCol) {
    for (let c = pc.value + dCol; c >= 0 && c < cols.value.length; c += dCol) {
      if (cellOk(pr.value, c)) { pc.value = c; return }
    }
  } else if (dRow) {
    for (let r = pr.value + dRow; r >= 0 && r < rows.value.length; r += dRow) {
      if (cellOk(r, pc.value)) { pr.value = r; return }
    }
  }
}

function onKey(e) {
  if (!previewVisible.value) return
  const map = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }
  const d = map[e.key]
  if (!d) return
  e.preventDefault()
  e.stopPropagation()
  step(d[0], d[1])
}

// 基线/对比批次选择(复用 store,与列表视图同一套状态)
function roleOf(id) {
  if (store.currentBatch?.id === id) return 'current'
  if (store.baselineBatch?.id === id) return 'baseline'
  return null
}

// 列宽按「全屏时面板可用宽度」标定,使列宽不随当前窗口拉伸而变:
//   - 窗口非占面板的部分(留白/滚动条)= innerWidth - 面板宽,与窗口大小无关;
//   - 全屏面板宽 ≈ 屏幕可用宽 - 该占用 → 据此 7 等分,全屏正好 7 列、其余尺寸下保持不变。
//   网页缩放(Ctrl±)由浏览器自身缩放固定的 CSS 像素列宽,图片随之放大/缩小;
//   MIN_COL/MAX_COL 给出最大最小约束。
function recalc() {
  const el = panel.value
  if (!el) return
  const chrome = Math.max(0, window.innerWidth - el.clientWidth)   // 面板以外占用(与窗口宽无关)
  const fullPanelW = (window.screen?.availWidth || window.innerWidth) - chrome
  const avail = fullPanelW - 24 - FIRST_COL - 8
  colW.value = Math.min(MAX_COL, Math.max(MIN_COL, Math.floor(avail / VISIBLE)))
}
let ro

onMounted(() => {
  ro = new ResizeObserver(recalc)
  if (panel.value) ro.observe(panel.value)
  recalc()
  // 用捕获阶段:抢在 Arco 灯箱自身的按键处理之前拿到方向键
  window.addEventListener('keydown', onKey, true)
  store.loadGridHeatmaps()   // keep-alive 返回 / 首屏:按当前选择恢复热力图列
})
onUnmounted(() => {
  ro?.disconnect()
  window.removeEventListener('keydown', onKey, true)
})
watch(cols, recalc)
// 选择变化 / 切场景(cols 变)时刷新热力图列(组件级兜底,store 内也会触发)
watch([currentBatch, baselineBatch, cols], () => store.loadGridHeatmaps())

const gridStyle = computed(() => ({
  gridTemplateColumns: `${FIRST_COL}px ` +
    cols.value.map((b) => (isCollapsed(b.id) ? COLLAPSED_W : colW.value) + 'px').join(' ') +
    ` ${colW.value}px`,   // 末列:差异热力图(吸附右侧)
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
        <div v-for="b in cols" :key="b.id" class="cell head"
          :class="{ collapsed: isCollapsed(b.id), 'role-base': roleOf(b.id) === 'baseline', 'role-cur': roleOf(b.id) === 'current' }">
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
              <div class="bsub"><span class="mono">#{{ b.id }}</span> · {{ p4Label(b.p4_version) }}</div>
              <div class="roles">
                <button class="role-btn base" :class="{ on: roleOf(b.id) === 'baseline' }"
                  @click="store.setRole(b, 'baseline')">基线</button>
                <button class="role-btn cur" :class="{ on: roleOf(b.id) === 'current' }"
                  @click="store.setRole(b, 'current')">对比</button>
              </div>
            </div>
          </template>
        </div>

        <!-- 末列表头:差异热力图(吸附右侧),展示已选基线/对比批次信息 -->
        <div class="cell head heat-head">
          <template v-if="bothSelected">
            <div class="heat-cmp">
              <div class="cmp-col base">
                <span class="cmp-pill base">基线</span>
                <span class="cmp-date">{{ baselineBatch.created_at.split(' ')[0] }}</span>
                <span class="cmp-p4">{{ p4Label(baselineBatch.p4_version) }}</span>
              </div>
              <div class="cmp-mid"><span class="cmp-vs">VS</span></div>
              <div class="cmp-col cur">
                <span class="cmp-pill cur">对比</span>
                <span class="cmp-date">{{ currentBatch.created_at.split(' ')[0] }}</span>
                <span class="cmp-p4">{{ p4Label(currentBatch.p4_version) }}</span>
              </div>
            </div>
            <div v-if="heatNoCache" class="heat-hint">尚无对比,此列为空</div>
          </template>
          <div v-else class="heat-empty">选择基线 / 对比批次</div>
        </div>

        <!-- 数据行:首列检查点名 + 各批次缩略图(原生 img,轻量) -->
        <template v-for="(r, rowIndex) in rows" :key="r.scene_name">
          <div class="cell rowhead" :title="r.scene_name" :style="{ height: imgH + 'px' }">{{ r.scene_name }}</div>
          <div v-for="(url, i) in r.cells" :key="cols[i].id" class="cell imgcell"
            :class="{ collapsed: isCollapsed(cols[i].id) }">
            <template v-if="!isCollapsed(cols[i].id)">
              <img v-if="url" class="thumb" :src="url" :alt="r.scene_name"
                loading="lazy" decoding="async" :style="{ height: imgH + 'px' }"
                @click="openPreview(rowIndex, i)" />
              <div v-else class="missing" :style="{ height: imgH + 'px' }">—</div>
            </template>
          </div>
          <!-- 末列:该检查点的差异热力图(吸附右侧) -->
          <div class="cell imgcell heat-cell">
            <template v-if="heatExists">
              <img v-if="heatUrl(r.scene_name)" :key="heatUrl(r.scene_name)" class="thumb"
                :src="heatUrl(r.scene_name)" :alt="r.scene_name"
                :style="{ height: imgH + 'px' }"
                @error="onHeatErr" @click="openHeatmap(heatUrl(r.scene_name))" />
              <div v-else class="missing" :style="{ height: imgH + 'px' }">—</div>
            </template>
            <div v-else class="heat-blank" :style="{ height: imgH + 'px' }"></div>
          </div>
        </template>
      </div>
      <!-- 放大后用方向键翻看:← → 跨批次,↑ ↓ 跨检查点(到边界不循环);关闭即卸载,避免残留遮罩/滚轮锁 -->
      <a-image-preview v-if="previewVisible" :src="previewSrc" :visible="true"
        @update:visible="previewVisible = $event" />
      <!-- 热力图单图放大(独立预览) -->
      <a-image-preview v-if="heatmapVisible" :src="heatmapSrc" :visible="true"
        @update:visible="heatmapVisible = $event" />
    </div>

    <!-- 放大时顶部显示当前图所属检查点 / 批次信息(叠在灯箱之上) -->
    <teleport to="body">
      <div v-if="previewVisible && previewMeta" class="preview-banner">
        <div class="pb-main">
          <span class="pb-scene">{{ previewMeta.scene_name }}</span>
          <span class="pb-meta">
            <span class="pb-date">{{ previewMeta.created_at }}</span>
            <span class="pb-dot">·</span>
            <span class="mono">批次 #{{ previewMeta.id }}</span>
            <span class="pb-dot">·</span>
            <span class="mono">{{ p4Label(previewMeta.p4_version) }}</span>
          </span>
        </div>
        <div class="pb-hint">
          <span class="pb-keys"><kbd>←</kbd><kbd>→</kbd></span>批次
          <span class="pb-keys"><kbd>↑</kbd><kbd>↓</kbd></span>检查点
        </div>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.grid-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0 12px 12px; }
.grid-scroll { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--color-border-2); border-radius: 8px; }
.matrix { display: grid; width: max-content; transition: grid-template-columns .16s ease; }

.cell {
  border-right: 1px solid var(--color-border-2);
  border-bottom: 1px solid var(--color-border-2);
  box-sizing: border-box;
}

/* 表头:吸顶(最小高度,折叠/展开不抖动;各表头随最高者一起拉伸,避免末列信息变高后留缝) */
.head {
  position: sticky; top: 0; z-index: 3;
  min-height: 84px; box-sizing: border-box;
  display: flex; flex-direction: column; justify-content: center;
  background: var(--color-bg-3); padding: 4px 8px;
}
/* 选为基线/对比的批次:表头按角色着色 + 顶部高亮条(color-mix 叠在不透明 bg-3 上,吸顶不透光) */
.head.role-base {
  background: color-mix(in srgb, rgb(var(--batch-base)) 15%, var(--color-bg-3));
  box-shadow: inset 0 3px 0 rgb(var(--batch-base));
}
.head.role-cur {
  background: color-mix(in srgb, rgb(var(--batch-cur)) 15%, var(--color-bg-3));
  box-shadow: inset 0 3px 0 rgb(var(--batch-cur));
}
/* 首列:吸左 */
.rowhead {
  position: sticky; left: 0; z-index: 2;
  background: var(--color-bg-2); padding: 8px 10px;
  display: flex; align-items: center;
  font-size: 12px; color: var(--color-text-2);
  overflow: hidden; word-break: break-all;   /* 长检查点名换行,不溢出列 */
}
/* 左上角:吸顶吸左,层级最高 */
.corner {
  position: sticky; top: 0; left: 0; z-index: 4;
  min-height: 84px; box-sizing: border-box;
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

/* contain:折叠动画逐帧改列宽时,把每个图片格的布局/重绘隔离在格内,
   避免重排/重绘扩散到整张矩阵,显著降低折叠时的卡顿 */
.imgcell { position: relative; z-index: 1; background: #0d1117; contain: layout paint; }
.cell.collapsed { padding: 0; overflow: hidden; background: var(--color-fill-2); }
/* 折叠列的表头吸顶,需不透明(fill-2 是半透明 token,叠在 bg-3 上避免透出滚动内容) */
.head.collapsed { background: linear-gradient(var(--color-fill-2), var(--color-fill-2)), var(--color-bg-3); }
.thumb { display: block; width: 100%; object-fit: cover; cursor: zoom-in; }
.missing { display: flex; align-items: center; justify-content: center; color: var(--color-text-4); }

/* 末列「差异热力图」:吸附右侧,横向滚动时常驻可见。
   right:-1px + border-right:0 让格子右缘略压到容器边框下,消除亚像素漏出的细缝。 */
.heat-head {
  position: sticky; top: 0; right: -1px; z-index: 5;
  border-right: 0; border-left: 2px solid rgb(var(--arcoblue-5));
  /* fill-2 是半透明 token,叠在不透明 bg-3 上得到不透明的浅色调,滚动时不透出内容 */
  background: linear-gradient(var(--color-fill-2), var(--color-fill-2)), var(--color-bg-3);
  height: auto; min-height: 84px;
  align-items: center; justify-content: center; gap: 6px; padding: 6px 8px;
}
/* 基线 / 对比 两栏,中间 VS 徽标 + 竖向分隔线,日期与 P4 按角色着色(参照对比结果卡片) */
.heat-cmp {
  display: grid; grid-template-columns: 1fr auto 1fr;
  align-items: center; gap: 4px; width: 100%;
}
.cmp-col { display: flex; flex-direction: column; align-items: center; gap: 3px; min-width: 0; }
.cmp-pill {
  font-size: 12px; font-weight: 700; line-height: 1.5;
  padding: 0 10px; border: 1px solid; border-radius: 6px; white-space: nowrap;
}
.cmp-pill.base { color: rgb(var(--batch-base)); border-color: rgb(var(--batch-base));
  background: color-mix(in srgb, rgb(var(--batch-base)) 12%, transparent); }
.cmp-pill.cur { color: rgb(var(--batch-cur)); border-color: rgb(var(--batch-cur));
  background: color-mix(in srgb, rgb(var(--batch-cur)) 12%, transparent); }
.cmp-date { font-size: 11px; font-weight: 600; white-space: nowrap; }
.cmp-p4 { font-size: 10px; white-space: nowrap; }
.cmp-col.base .cmp-date, .cmp-col.base .cmp-p4 { color: rgb(var(--batch-base)); }
.cmp-col.cur .cmp-date, .cmp-col.cur .cmp-p4 { color: rgb(var(--batch-cur)); }
/* 中间竖线 + VS 徽标 */
.cmp-mid { position: relative; align-self: stretch; display: flex; align-items: center; justify-content: center; width: 24px; }
.cmp-mid::before { content: ''; position: absolute; top: 6px; bottom: 6px; width: 1px; background: var(--color-border-2); }
.cmp-vs {
  position: relative; z-index: 1;
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%;
  font-size: 10px; font-weight: 700; color: var(--color-text-3);
  background: var(--color-bg-3); border: 1px solid var(--color-border-2);
}
.heat-hint { font-size: 10px; color: var(--color-text-3); text-align: center; }
.heat-empty { flex: 1; display: flex; align-items: center; justify-content: center;
  text-align: center; font-size: 11px; color: var(--color-text-3); }
.heat-cell { position: sticky; right: -1px; z-index: 2; border-right: 0;
  border-left: 2px solid rgb(var(--arcoblue-5));   /* 整列左侧蓝色分隔条,与批次列区分 */
  contain: none; }   /* 覆盖 .imgcell 的 contain:paint:对比完就地注入图片时避免延迟重绘(黑块) */
.heat-blank { background: var(--color-fill-1); }

/* 放大灯箱顶部的批次信息条(teleport 到 body,仍受 scoped 作用) */
.preview-banner {
  position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
  z-index: 100000; pointer-events: none;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 9px 18px; border-radius: 10px;
  background: rgba(0, 0, 0, .66); color: #fff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, .3);
}
.preview-banner .pb-main { display: flex; align-items: baseline; gap: 10px; }
.preview-banner .pb-scene { font-size: 14px; font-weight: 600; letter-spacing: .2px; }
.preview-banner .pb-meta { display: flex; align-items: center; gap: 7px; font-size: 12px; color: rgba(255, 255, 255, .72); }
.preview-banner .pb-date { color: rgb(var(--arcoblue-5)); font-weight: 600; }
.preview-banner .pb-dot { opacity: .4; }
.preview-banner .pb-hint {
  display: flex; align-items: center; gap: 5px;
  width: 100%; justify-content: center;
  padding-top: 6px; border-top: 1px solid rgba(255, 255, 255, .14);
  font-size: 11px; color: rgba(255, 255, 255, .58);
}
.preview-banner .pb-keys { display: inline-flex; gap: 2px; margin-right: 1px; }
.preview-banner kbd {
  display: inline-block; min-width: 16px; text-align: center;
  padding: 1px 4px; border-radius: 4px; line-height: 1.5;
  font-family: inherit; font-size: 11px;
  background: rgba(255, 255, 255, .16); border: 1px solid rgba(255, 255, 255, .22);
}
</style>
