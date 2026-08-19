<script setup>
import { ref, computed, nextTick, onActivated, onDeactivated, onMounted, onUnmounted, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { p4Label } from '../store'
import { useScreenshotComparisonStore } from '../stores/screenshotComparisonStore'
import { thumbUrl } from '../api'
import { splitCheckpointName } from './checkpointName'

// 缩略图加载失败时回退原图(只回退一次,防循环)
function onThumbErr(e, orig) {
  const img = e.target
  if (img.dataset.fb || !orig) return
  img.dataset.fb = '1'
  img.src = orig
}

const store = useScreenshotComparisonStore()
const cols = computed(() => store.grid.batches)
const rows = computed(() => store.grid.rows.map((row) => ({
  ...row,
  checkpointName: splitCheckpointName(row.scene_name),
})))

const FIRST_COL = 100         // 首列(检查点编号)固定宽
const VISIBLE_BATCHES = 7     // 全屏时完整展示的批次列数
const VISIBLE_IMAGE_COLS = VISIBLE_BATCHES + 1  // 额外预留最右差异热力图列
const COLLAPSED_W = 18        // 折叠后列宽(细条)
const MIN_COL = 120           // 列宽下限
const panel = ref(null)
const scroll = ref(null)      // 滚动容器(用于拖拽平移)
const matrix = ref(null)      // 实际网格(监听异步数据/列宽动画导致的宽度增长)
const colW = ref(160)         // 单个批次列宽(按当前网格可视宽度动态适配)
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
const heatExists = computed(() => !!(heatForPair.value?.exists && heatForPair.value?.ready))
const heatNoCache = computed(() => heatForPair.value?.status === 'missing')
const heatRunning = computed(() => heatForPair.value?.status === 'running' || store.running)
const heatUrl = (sceneName) => (heatExists.value ? heatForPair.value.map[sceneName] || '' : '')

// 刚算完的热力图文件可能有极短的落盘/服务竞态导致首次 404,失败后带缓存戳重试几次
function onHeatErr(e) {
  const img = e.target
  const n = Number(img.dataset.retry || 0)
  if (n >= 3) return
  img.dataset.retry = n + 1
  const base = img.src.split('?')[0]
  setTimeout(() => { img.src = `${base}?r=${Date.now()}` }, 300 * (n + 1))
}

// 拖拽平移:按住矩阵上下左右拖动滚动;移动超过阈值才算拖拽(并吞掉尾随 click,避免误触放大)
const grabbing = ref(false)
let panning = false, moved = false, startX = 0, startY = 0, startLeft = 0, startTop = 0
function onPanDown(e) {
  if (e.button !== 0 || previewVisible.value) return   // 仅左键;放大灯箱开启时不平移
  if (e.target.closest('.head, .rowhead')) return      // 表头行 + 检查点名首列(整个框)不参与拖拽,仅图片区域可拖
  const el = scroll.value
  if (!el) return
  e.preventDefault()   // 阻止浏览器对 <img> 的原生拖拽(否则会吞掉 mousemove/mouseup,导致拖不动且状态卡住)
  panning = true; moved = false
  startX = e.clientX; startY = e.clientY
  startLeft = el.scrollLeft; startTop = el.scrollTop
  window.addEventListener('mousemove', onPanMove, true)
  window.addEventListener('mouseup', onPanUp, true)
}
function onPanMove(e) {
  if (!panning) return
  const dx = e.clientX - startX, dy = e.clientY - startY
  if (!moved && Math.hypot(dx, dy) > 5) { moved = true; grabbing.value = true }
  if (moved) {
    e.preventDefault()
    scroll.value.scrollLeft = startLeft - dx
    scroll.value.scrollTop = startTop - dy
  }
}
function onPanUp() {
  window.removeEventListener('mousemove', onPanMove, true)
  window.removeEventListener('mouseup', onPanUp, true)
  if (moved) {
    // 吞掉这次拖拽尾随的 click(捕获阶段),避免触发图片放大
    const swallow = (ev) => { ev.stopPropagation(); ev.preventDefault() }
    window.addEventListener('click', swallow, true)
    setTimeout(() => window.removeEventListener('click', swallow, true), 0)
  }
  panning = false; moved = false; grabbing.value = false
}

// 折叠的批次列(放在 store,按批次 id;跨刷新/改筛选/切场景保留)
const isCollapsed = (id) => store.gridCollapsed.has(id)
const retryGrid = () => store.loadGrid().catch(() => {})
let columnAnchorRun = 0
// 折叠时按可视图片区就近选择左右锚点；展开复用同一批次记录，避免方向翻转。
const columnAnchorSides = new Map()

function chooseColumnAnchor(head) {
  const el = scroll.value
  if (!el) return 'right'
  const columnRect = head.getBoundingClientRect()
  const viewportRect = el.getBoundingClientRect()
  const visibleLeft = viewportRect.left + FIRST_COL
  const visibleRight = viewportRect.right - colW.value
  const center = (columnRect.left + columnRect.right) / 2
  return Math.abs(center - visibleLeft) <= Math.abs(visibleRight - center) ? 'left' : 'right'
}

function keepColumnAnchored(head, side, anchorPosition) {
  const run = ++columnAnchorRun
  nextTick(() => {
    let frames = 0
    const step = () => {
      const el = scroll.value
      if (run !== columnAnchorRun || !el || !head.isConnected) return
      const rect = head.getBoundingClientRect()
      const delta = rect[side] - anchorPosition
      if (Math.abs(delta) > 0.01) el.scrollLeft += delta
      frames += 1
      if (frames < 20) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  })
}

function toggle(id, event) {
  stopAutoPin()
  const head = event?.currentTarget?.closest('.head')
  const s = store.gridCollapsed
  const expanding = s.has(id)
  const side = expanding
    ? columnAnchorSides.get(id) || (head ? chooseColumnAnchor(head) : 'right')
    : (head ? chooseColumnAnchor(head) : 'right')
  const anchorPosition = head?.getBoundingClientRect()[side]

  if (expanding) {
    s.delete(id)
    columnAnchorSides.delete(id)
  } else {
    s.add(id)
    columnAnchorSides.set(id, side)
  }
  if (head && Number.isFinite(anchorPosition)) keepColumnAnchored(head, side, anchorPosition)
}

// 受控预览:点击缩略图后在整个矩阵里用方向键二维翻看
//(缩略图用原生 img 渲染,避免上千个重组件;放大体验不变)
//   ← →  同一检查点的不同批次(跨列)   ↑ ↓  同一批次的不同检查点(跨行)
//   到边界不循环。跳过空格(无图)与已折叠的列。
const previewVisible = ref(false)
const previewScale = ref(1)   // 同一次大图浏览期间共享；关闭后恢复默认
const previewTranslate = ref([0, 0])
const previewComponent = ref(null)
const pr = ref(0)   // 当前行(检查点)下标
const pc = ref(0)   // 当前列(批次)下标
let restoringPreviewTransform = false

// 列索引 == cols.length 表示最右侧「差异热力图」虚拟列
const isHeatCol = (c) => c === cols.value.length
function previewUrlAt(rowIndex, colIndex) {
  const row = rows.value[rowIndex]
  if (!row) return ''
  if (isHeatCol(colIndex)) return heatUrl(row.scene_name)
  return row.cells[colIndex] || ''
}
const previewSrc = computed(() => previewUrlAt(pr.value, pc.value))

// Arco 未公开受控的 scale/translate 属性，但组件实例提供了其响应式内部状态。
// 用户滚轮缩放或拖动时同步记录；切换 src 后再写回，避免只改 CSS 导致后续拖动跳位。
watch(
  () => {
    const preview = previewComponent.value
    return preview ? [preview.scale, ...(preview.translate || [0, 0])] : null
  },
  (transform) => {
    if (!transform || restoringPreviewTransform || !previewVisible.value) return
    const [scale, x, y] = transform.map(Number)
    if (Number.isFinite(scale)) previewScale.value = scale
    if (Number.isFinite(x) && Number.isFinite(y)) previewTranslate.value = [x, y]
  },
  { flush: 'sync' },
)

watch(previewSrc, async (src, previousSrc) => {
  if (!previewVisible.value || !previousSrc || src === previousSrc) return
  const scale = previewScale.value
  const translate = [...previewTranslate.value]
  restoringPreviewTransform = true
  await nextTick()   // 等待 Arco 因 src 变化执行 reset()
  const preview = previewComponent.value
  if (preview) {
    preview.scale = scale
    preview.translate = translate
  }
  await nextTick()
  restoringPreviewTransform = false
})
const previewMeta = computed(() => {
  const row = rows.value[pr.value]
  if (!row) return null
  if (isHeatCol(pc.value)) {
    return { scene_name: row.scene_name, isHeat: true,
             baseId: baselineBatch.value?.id, curId: currentBatch.value?.id }
  }
  const b = cols.value[pc.value]
  if (!b) return null
  return { scene_name: row.scene_name, created_at: b.created_at, id: b.id, p4_version: b.p4_version, shading_quality_label: b.shading_quality_label }
})

// 该格是否可作为导航落点:有图、列未折叠;热力图虚拟列需该行有合法热力图
function cellOk(r, c) {
  const row = rows.value[r]
  if (!row) return false
  if (isHeatCol(c)) return heatExists.value && !!previewUrlAt(r, c)
  if (!previewUrlAt(r, c)) return false
  const b = cols.value[c]
  return !!b && !isCollapsed(b.id)
}

// 与方向键共用同一寻址规则：跳过空格和折叠列，找到该方向最近的有效图片。
function findPreviewTarget(rowIndex, colIndex, dRow, dCol) {
  let r = rowIndex + dRow
  let c = colIndex + dCol
  while (r >= 0 && r < rows.value.length && c >= 0 && c <= cols.value.length) {
    if (cellOk(r, c)) return { rowIndex: r, colIndex: c }
    r += dRow
    c += dCol
  }
  return null
}

const PREVIEW_PRELOAD_CONCURRENCY = 2
const PREVIEW_IMAGE_TIMEOUT_MS = 30_000
const PREVIEW_PRELOAD_DIRECTIONS = [
  [0, -1], // 左右优先：同一检查点跨批次对比更常用
  [0, 1],
  [-1, 0],
  [1, 0],
]
let currentImageProbe = null
let currentImageProbeTimer = null
let currentImageProbeRun = 0
let previewPreloadQueue = []
const previewPreloadActive = new Map()
const previewPreloadSeen = new Set()
const previewPreloadLoaded = new Set()

function detachPreloadImage(image) {
  image.onload = null
  image.onerror = null
  // Image 没有 AbortController；移除 src 可尽力停止未完成请求，回调序号仍负责最终隔离。
  try { image.removeAttribute?.('src') } catch { /* 浏览器不支持时仅失效回调 */ }
}

function cancelCurrentImageProbe() {
  currentImageProbeRun += 1
  if (currentImageProbeTimer !== null) {
    clearTimeout(currentImageProbeTimer)
    currentImageProbeTimer = null
  }
  if (!currentImageProbe) return
  detachPreloadImage(currentImageProbe)
  currentImageProbe = null
}

function stopPreviewPreloading() {
  cancelCurrentImageProbe()
  previewPreloadQueue = []
  for (const task of [...previewPreloadActive.values()]) {
    detachPreloadImage(task.image)
    task.finish(false)
  }
  previewPreloadActive.clear()
  previewPreloadSeen.clear()
  previewPreloadLoaded.clear()
}

function pumpPreviewPreloads() {
  while (previewPreloadActive.size < PREVIEW_PRELOAD_CONCURRENCY && previewPreloadQueue.length) {
    const url = previewPreloadQueue.shift()
    if (!url || previewPreloadSeen.has(url)) continue
    const image = new Image()
    image.decoding = 'async'
    let resolveDone
    const task = {
      image,
      settled: false,
      done: new Promise((resolve) => { resolveDone = resolve }),
      timer: null,
      finish(loaded) {
        if (task.settled) return
        task.settled = true
        if (task.timer !== null) clearTimeout(task.timer)
        task.timer = null
        image.onload = null
        image.onerror = null
        if (loaded) previewPreloadLoaded.add(url)
        if (previewPreloadActive.get(url) === task) previewPreloadActive.delete(url)
        resolveDone(loaded)
        pumpPreviewPreloads()
      },
    }
    image.onload = () => task.finish(true)
    image.onerror = () => task.finish(false) // 后台失败静默跳过；真正打开时仍由灯箱正常请求
    previewPreloadSeen.add(url)
    previewPreloadActive.set(url, task)
    task.timer = setTimeout(() => {
      detachPreloadImage(image)
      task.finish(false)
    }, PREVIEW_IMAGE_TIMEOUT_MS)
    image.src = url
  }
}

function replacePreviewPreloadQueue(urls) {
  previewPreloadQueue = []
  const queued = new Set()
  for (const url of urls) {
    if (!url || previewPreloadSeen.has(url) || queued.has(url)) continue
    queued.add(url)
    previewPreloadQueue.push(url)
  }
  pumpPreviewPreloads()
}

function previewNeighborUrls() {
  return PREVIEW_PRELOAD_DIRECTIONS.flatMap(([dRow, dCol]) => {
    const target = findPreviewTarget(pr.value, pc.value, dRow, dCol)
    return target ? [previewUrlAt(target.rowIndex, target.colIndex)] : []
  })
}

// 灯箱和探针请求同一 URL，浏览器会合并网络请求；只有当前图成功后才启动相邻预加载。
function probeCurrentImage(src) {
  cancelCurrentImageProbe()
  previewPreloadQueue = []       // 快速切图时丢弃尚未启动的旧位置预加载
  if (!src) return
  const run = currentImageProbeRun
  const finish = (loaded) => {
    if (!loaded || run !== currentImageProbeRun || !previewVisible.value || previewSrc.value !== src) return
    previewPreloadSeen.add(src)
    previewPreloadLoaded.add(src)
    replacePreviewPreloadQueue(previewNeighborUrls())
  }

  // 已由本次灯箱会话加载完成，或正在作为相邻图加载时，直接复用结果，不再创建重复 Image。
  if (previewPreloadLoaded.has(src)) {
    Promise.resolve().then(() => finish(true))
    return
  }
  const activeTask = previewPreloadActive.get(src)
  if (activeTask) {
    activeTask.done.then(finish)
    return
  }

  const image = new Image()
  image.decoding = 'async'
  currentImageProbe = image
  const finishProbe = (loaded) => {
    if (currentImageProbeTimer !== null) {
      clearTimeout(currentImageProbeTimer)
      currentImageProbeTimer = null
    }
    if (currentImageProbe === image) currentImageProbe = null
    image.onload = null
    image.onerror = null
    finish(loaded)
  }
  image.onload = () => finishProbe(true)
  image.onerror = () => finishProbe(false)
  currentImageProbeTimer = setTimeout(() => {
    detachPreloadImage(image)
    finishProbe(false)
  }, PREVIEW_IMAGE_TIMEOUT_MS)
  image.src = src
}

function openPreview(rowIndex, colIndex) {
  pr.value = rowIndex
  pc.value = colIndex
  previewScale.value = 1
  previewTranslate.value = [0, 0]
  previewVisible.value = true
}

function setPreviewVisible(visible) {
  previewVisible.value = visible
  if (!visible) {
    stopPreviewPreloading()
    previewScale.value = 1
    previewTranslate.value = [0, 0]
  }
}

// 朝某方向找下一个可落点;找不到就停在原地(不循环)
function step(dRow, dCol) {
  const target = findPreviewTarget(pr.value, pc.value, dRow, dCol)
  if (!target) return
  pr.value = target.rowIndex
  pc.value = target.colIndex
}

watch([previewVisible, previewSrc], ([visible, src]) => {
  if (!visible || !src) {
    stopPreviewPreloading()
    return
  }
  probeCurrentImage(src)
}, { flush: 'post' }) // 先让灯箱挂载当前原图，再用同 URL 探针等待其完成

function onKey(e) {
  if (!previewVisible.value) return
  if (e.key === 'Escape') { setPreviewVisible(false); return }   // ESC 退出大图
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
// 列头单按钮(按全局选择状态决定):未选基线→设为基线;已选基线未选对比→设为对比;
// 已是基线/对比→再点取消;两者都选→未选列点击重设基线。
function roleBtnText(id) {
  const r = roleOf(id)
  if (r === 'baseline') return '基线'
  if (r === 'current') return '对比'
  return store.baselineBatch ? '设为对比' : '设为基线'   // 有基线 → 其余列都「设为对比」
}
function roleBtnKind(id) {            // 着色:base / cur
  const r = roleOf(id)
  if (r) return r === 'baseline' ? 'base' : 'cur'
  return store.baselineBatch ? 'cur' : 'base'
}
function onRoleBtn(b) {
  const r = roleOf(b.id)
  if (r) return store.clearRole(r)                          // 已选 → 取消
  if (!store.baselineBatch) return store.setRole(b, 'baseline')
  return store.setRole(b, 'current')                        // 有基线 → 设为对比(含替换原对比)
}

// 发起对比(截图网格内,入口在热力图表头按钮);同场景天然成立,无需跨场景守卫
async function runCompare(force = false) {
  if (!store.canCompare || store.running) return
  try {
    const result = await store.runComparison({ force })
    if (result?.ready || result?.status === 'done') Message.success('对比完成')
  } catch (e) {
    Message.error(e.message || '对比失败')
  }
}

// 按网格真实可视宽度动态计算列宽：扣除检查点列后 8 等分，
// 正好容纳 7 个批次列 + 1 个差异热力图列。使用 scroll.clientWidth
// 可自动扣除边框和纵向滚动条，不依赖屏幕物理分辨率或系统缩放。
function recalc() {
  const el = panel.value
  if (!el) return
  const viewportW = scroll.value?.clientWidth || el.clientWidth
  const availableForImages = Math.max(0, viewportW - FIRST_COL)
  const fittedWidth = Math.round((availableForImages / VISIBLE_IMAGE_COLS) * 100) / 100
  const nextColW = Math.max(MIN_COL, fittedWidth)
  if (nextColW === colW.value) return
  colW.value = nextColW
}
let ro

// 截图网格默认停在最右(最新批次在右);仅切场景/首屏/keep-alive 返回时滚,自动刷新不打断
let pendingScrollRight = true
let pendingScrollTop = false
const autoPinRight = ref(true)

function stopAutoPin() {
  autoPinRight.value = false
}

function onGridScroll() {
  const el = scroll.value
  if (!autoPinRight.value || !el) return
  const max = el.scrollWidth - el.clientWidth
  if (max - el.scrollLeft <= 1) return
  requestAnimationFrame(() => {
    if (autoPinRight.value && scroll.value) scroll.value.scrollLeft = scroll.value.scrollWidth
  })
}

function scrollToRight() {
  // 逐帧把 scrollLeft 追到当前 scrollWidth,直到宽度不再变——覆盖列宽过渡
  // (.matrix transition .16s)与 keep-alive 返回时布局未稳,避免停在中间。
  nextTick(() => {
    let last = -1, tries = 0
    const initial = scroll.value
    if (initial) initial.scrollLeft = initial.scrollWidth
    const step = () => {
      const el = scroll.value
      if (!el) return
      el.scrollLeft = el.scrollWidth
      if (el.scrollWidth !== last && tries < 20) {
        last = el.scrollWidth
        tries += 1
        requestAnimationFrame(step)
      }
    }
    requestAnimationFrame(step)
  })
}

function scrollToTop() {
  nextTick(() => {
    if (scroll.value) scroll.value.scrollTop = 0
  })
}

onMounted(() => {
  ro = new ResizeObserver(() => {
    recalc()
    // 全屏刷新时面板、列数据和列宽动画可能分批稳定；矩阵每次增宽都继续追到最右。
    if (autoPinRight.value) scrollToRight()
  })
  if (panel.value) ro.observe(panel.value)
  if (scroll.value) ro.observe(scroll.value)
  if (matrix.value) ro.observe(matrix.value)
  recalc()
  // 用捕获阶段:抢在 Arco 灯箱自身的按键处理之前拿到方向键
  window.addEventListener('keydown', onKey, true)
  if (cols.value.length && pendingScrollRight) { pendingScrollRight = false; scrollToRight() }
})
watch(matrix, (next, previous) => {
  if (!ro) return
  if (previous) ro.unobserve(previous)
  if (next) ro.observe(next)
})
// keep-alive 返回截图对比时，网格仍停到最右看最新
onActivated(() => {
  autoPinRight.value = true
  if (cols.value.length) scrollToRight()
})
onDeactivated(() => {
  store.cancelGridHeatmapRequest()
  setPreviewVisible(false)
})
onUnmounted(() => {
  store.cancelGridHeatmapRequest()
  stopPreviewPreloading()
  columnAnchorRun += 1
  columnAnchorSides.clear()
  ro?.disconnect()
  window.removeEventListener('keydown', onKey, true)
  window.removeEventListener('mousemove', onPanMove, true)
  window.removeEventListener('mouseup', onPanUp, true)
})
watch(cols, () => {
  const visibleIds = new Set(cols.value.map((batch) => batch.id))
  for (const id of columnAnchorSides.keys()) {
    if (!visibleIds.has(id)) columnAnchorSides.delete(id)
  }
  recalc()
  // 数据到位且处于"待滚动"(切场景/首屏)时,定位到最右看最新;自动刷新不会置位,故不打断
  if (pendingScrollRight && cols.value.length) {
    pendingScrollRight = false
    scrollToRight()
  }
  if (pendingScrollTop && cols.value.length) {
    pendingScrollTop = false
    scrollToTop()
  }
})

// 仅切换场景 ID 时统一回到第一行；立即重置一次，并在新矩阵到位后再次确认，
// 覆盖旧 DOM 被加载态替换或浏览器因高度变化重新钳制 scrollTop 的情况。
watch(() => store.filters.scene_id, () => {
  setPreviewVisible(false)
  pendingScrollTop = true
  pendingScrollRight = true
  autoPinRight.value = true
  scrollToTop()
})

// 画质 / 创建时间变化仍只重新定位到最右看最新，不改变纵向浏览位置；
// 自动刷新不碰这些筛选字段，也不会打断用户的滚动位置。
watch(() => [
  store.filters.shading_quality,
  store.filters.created_from,
  store.filters.created_to,
  store.filters.created_dates,
], () => {
  pendingScrollRight = true
  autoPinRight.value = true
}, { deep: true })
const gridStyle = computed(() => ({
  gridTemplateColumns: `${FIRST_COL}px ` +
    cols.value.map((b) => (isCollapsed(b.id) ? COLLAPSED_W : colW.value) + 'px').join(' ') +
    ` ${colW.value}px`,   // 末列:差异热力图(吸附右侧)
}))
</script>

<template>
  <div class="grid-panel" ref="panel">
    <a-empty v-if="!store.filters.scene_id" description="请先在上方筛选条选择一个场景" style="margin-top: 60px" />
    <div v-else-if="store.gridError" class="grid-state">
      <div class="grid-state-title">截图网格加载失败</div>
      <div class="grid-state-message">{{ store.gridError }}</div>
      <a-button type="primary" size="small" @click="retryGrid">重新加载</a-button>
    </div>
    <div v-else-if="store.gridLoading && !cols.length" class="grid-state">
      <a-spin :size="28" tip="正在加载截图网格…" />
    </div>
    <a-empty v-else-if="!cols.length" description="当前分支和场景下没有包含截图的批次" style="margin-top: 60px" />
    <div v-else class="grid-scroll" :class="{ grabbing, 'auto-positioning': autoPinRight }" ref="scroll"
      @scroll.passive="onGridScroll" @pointerdown.passive="stopAutoPin" @wheel.passive="stopAutoPin"
      @mousedown="onPanDown">
      <div class="matrix" ref="matrix" :style="gridStyle">
        <!-- 表头行:左上角 + 每个批次 -->
        <div class="cell head corner">
          <span class="corner-batch">批次</span>
          <span class="corner-checkpoint">检查点</span>
        </div>
        <div v-for="b in cols" :key="b.id" class="cell head"
          :class="{ collapsed: isCollapsed(b.id), 'role-base': roleOf(b.id) === 'baseline', 'role-cur': roleOf(b.id) === 'current' }">
          <button v-if="isCollapsed(b.id)" class="expand" :title="'展开 #' + b.id" @click="toggle(b.id, $event)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
              stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
          </button>
          <template v-else>
            <button class="collapse-btn" title="折叠此列" @click="toggle(b.id, $event)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14" /></svg>
            </button>
            <div class="bhead">
              <div class="dateline">
                <span class="date">{{ b.created_at.split(' ')[0] }}</span>
                <span class="dtime">{{ b.created_at.split(' ')[1] }}</span>
              </div>
              <div class="bsub"><span class="mono">#{{ b.id }}</span> · {{ p4Label(b.p4_version) }} · {{ b.shading_quality_label }}</div>
              <div class="roles">
                <button class="role-btn" :class="[roleBtnKind(b.id), { on: !!roleOf(b.id) }]"
                  @click="onRoleBtn(b)">{{ roleBtnText(b.id) }}</button>
              </div>
            </div>
          </template>
        </div>

        <!-- 末列表头:差异热力图(吸附右侧),展示已选基线/对比批次信息 -->
        <div class="cell head heat-head">
          <div class="heat-title" :class="{ 'is-btn': bothSelected && heatNoCache }">
            <a-spin v-if="bothSelected && store.gridHeatmapLoading" :size="16" />
            <a-button v-else-if="bothSelected && store.gridHeatmapError" size="mini" long
              @click="store.loadGridHeatmaps()">查询失败，重试</a-button>
            <span v-else-if="bothSelected && heatRunning" class="heat-running">
              {{ store.progress.total ? `对比中 ${store.progress.done}/${store.progress.total}` : '对比中…' }}
            </span>
            <a-button v-else-if="bothSelected && heatNoCache" type="primary" size="mini" long
              :loading="store.running" :disabled="!store.canCompare || store.running" @click="runCompare(false)">
              {{ store.running && store.progress.total ? `对比中 ${store.progress.done}/${store.progress.total}` : '发起对比' }}
            </a-button>
            <span v-else-if="heatExists" class="heat-title-ready">
              <span class="heat-title-dot"></span>差异热力图
              <button class="rerun-link" :disabled="store.running" @click="runCompare(true)">重新对比</button>
            </span>
            <template v-else><span class="heat-title-dot"></span>差异对比</template>
          </div>
          <div class="heat-body">
            <template v-if="bothSelected">
              <div class="heat-cmp">
                <div class="cmp-col base">
                  <span class="cmp-pill base">基线</span>
                  <span class="cmp-date">{{ baselineBatch.created_at.split(' ')[0] }}</span>
                  <span class="cmp-p4">{{ p4Label(baselineBatch.p4_version) }} · {{ baselineBatch.shading_quality_label }}</span>
                </div>
                <div class="cmp-mid"><span class="cmp-vs">VS</span></div>
                <div class="cmp-col cur">
                  <span class="cmp-pill cur">对比</span>
                  <span class="cmp-date">{{ currentBatch.created_at.split(' ')[0] }}</span>
                  <span class="cmp-p4">{{ p4Label(currentBatch.p4_version) }} · {{ currentBatch.shading_quality_label }}</span>
                </div>
              </div>
            </template>
            <div v-else class="heat-empty">选择基线 / 对比批次</div>
          </div>
        </div>

        <!-- 数据行:首列检查点编号 + 各批次缩略图(原生 img,轻量) -->
        <template v-for="(r, rowIndex) in rows" :key="r.scene_name">
          <div class="cell rowhead" :title="r.scene_name">
            <span v-if="r.checkpointName.index" class="rowhead-index mono">{{ r.checkpointName.index }}</span>
            <span v-else class="rowhead-name">{{ r.checkpointName.name }}</span>
          </div>
          <div v-for="(url, i) in r.cells" :key="cols[i].id" class="cell imgcell"
            :class="{ collapsed: isCollapsed(cols[i].id) }">
            <template v-if="!isCollapsed(cols[i].id)">
              <img v-if="url" class="thumb" :src="thumbUrl(url)" :alt="r.scene_name" draggable="false"
                loading="lazy" decoding="async" :style="{ height: imgH + 'px' }"
                @error="onThumbErr($event, url)" @click="openPreview(rowIndex, i)" />
              <div v-else class="missing" :style="{ height: imgH + 'px' }">—</div>
            </template>
          </div>
          <!-- 末列:该检查点的差异热力图(吸附右侧) -->
          <div class="cell imgcell heat-cell">
            <template v-if="heatExists">
              <img v-if="heatUrl(r.scene_name)" :key="heatUrl(r.scene_name)" class="thumb"
                :src="heatUrl(r.scene_name)" :alt="r.scene_name" draggable="false"
                :style="{ height: imgH + 'px' }"
                @error="onHeatErr" @click="openPreview(rowIndex, cols.length)" />
              <div v-else class="missing" :style="{ height: imgH + 'px' }">—</div>
            </template>
            <div v-else class="heat-blank" :style="{ height: imgH + 'px' }"></div>
          </div>
        </template>
      </div>
      <!-- 放大后用方向键翻看:← → 跨批次,↑ ↓ 跨检查点(到边界不循环);关闭即卸载,避免残留遮罩/滚轮锁 -->
      <a-image-preview v-if="previewVisible" ref="previewComponent" :src="previewSrc" :visible="true"
        :default-scale="previewScale" @update:visible="setPreviewVisible" />
    </div>

    <!-- 放大时顶部显示当前图所属检查点 / 批次信息(叠在灯箱之上) -->
    <teleport to="body">
      <div v-if="previewVisible && previewMeta" class="preview-banner">
        <div class="pb-main">
          <span class="pb-scene">{{ previewMeta.scene_name }}</span>
          <span v-if="previewMeta.isHeat" class="pb-meta">
            <span class="pb-date">差异热力图</span>
            <span class="pb-dot">·</span>
            <span class="mono">基线 #{{ previewMeta.baseId }}</span>
            <span class="pb-dot">VS</span>
            <span class="mono">对比 #{{ previewMeta.curId }}</span>
          </span>
          <span v-else class="pb-meta">
            <span class="pb-date">{{ previewMeta.created_at }}</span>
            <span class="pb-dot">·</span>
            <span class="mono">批次 #{{ previewMeta.id }}</span>
            <span class="pb-dot">·</span>
            <span class="mono">{{ p4Label(previewMeta.p4_version) }}</span>
            <span class="pb-dot">·</span>
            <span>{{ previewMeta.shading_quality_label }}</span>
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
.grid-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0 0 12px; }
.grid-state {
  flex: 1; min-height: 160px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 9px;
}
.grid-state-title { color: var(--color-text-1); font-size: 14px; font-weight: 600; }
.grid-state-message { max-width: 520px; color: var(--color-text-3); font-size: 12px; text-align: center; }
.grid-scroll { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--color-border-2); border-radius: 8px; cursor: default; }
/* 拖拽平移进行中:统一抓手光标(覆盖图片的 zoom-in),并禁止选中 */
.grid-scroll.grabbing { cursor: grabbing; user-select: none; }
.grid-scroll.grabbing * { cursor: grabbing !important; }
.grid-scroll.auto-positioning .matrix { transition: none; }
/* 表头行 + 检查点名首列不可拖,光标恢复默认(内部按钮自带 pointer 不受影响) */
.head, .rowhead { cursor: default; }
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
  display: flex; align-items: center; justify-content: center; text-align: center;
  font-size: 12px; color: var(--color-text-2);
  overflow: hidden;
}
.rowhead-name {
  display: block; max-width: 100%; overflow: hidden;
  white-space: nowrap; text-overflow: ellipsis; line-height: 1.35;
}
.rowhead-index {
  display: block; font-size: 13px; line-height: 1.2; letter-spacing: .4px;
  color: var(--color-text-3); font-weight: 400;
}
/* 左上角:吸顶吸左,层级最高 */
.corner {
  position: sticky; top: 0; left: 0; z-index: 4;
  min-height: 84px; box-sizing: border-box;
  display: block; background: var(--color-bg-3); padding: 0;
  font-size: 12px; color: var(--color-text-3);
}
.corner::before {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(to bottom left,
    transparent calc(50% - .5px),
    var(--color-border-2) 50%,
    transparent calc(50% + .5px));
}
.corner-batch, .corner-checkpoint { position: absolute; z-index: 1; line-height: 1; }
.corner-batch { top: 18px; right: 18px; }
.corner-checkpoint { bottom: 18px; left: 18px; }

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
  font-size: 12px; padding: 3px 10px; border-radius: 5px; line-height: 1.5; font-family: inherit;
  min-width: 70px; box-sizing: border-box; text-align: center;   /* 「基线」与「设为基线」等宽对齐 */
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
  height: 94px; overflow: hidden;   /* 固定高度:发起对比按钮 / 空态提示切换时表头不抖动 */
  flex-direction: column; align-items: stretch; justify-content: flex-start; gap: 0; padding: 0;
}
/* 顶部「差异对比」标题条:贯穿整列、蓝色强调 + 下分隔线 */
.heat-title {
  display: flex; align-items: center; justify-content: center;
  height: 32px; box-sizing: border-box; padding: 0 8px;   /* 固定高度:标题文字 / 发起对比按钮两态等高,下方卡片对齐 */
  border-bottom: 1px solid var(--color-border-2);
  font-size: 12px; font-weight: 700; letter-spacing: .3px;
  color: rgb(var(--arcoblue-6));
}
.heat-title-dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  background: rgb(var(--arcoblue-5)); margin-right: 5px; vertical-align: -1px;
}
.heat-title-ready, .heat-running { display: inline-flex; align-items: center; }
.heat-running { color: var(--color-text-2); font-weight: 500; }
.rerun-link {
  margin-left: 8px; padding: 0; border: 0; background: none; cursor: pointer;
  color: var(--color-text-3); font: inherit; font-size: 10px; font-weight: 500;
}
.rerun-link:hover { color: rgb(var(--arcoblue-5)); }
.rerun-link:disabled { cursor: default; opacity: .45; }
/* 按钮态:让「发起对比」按钮撑满标题条(高度仍由 .heat-title 固定,保证两态等高) */
.heat-title.is-btn { padding: 0 6px; }
.heat-title.is-btn :deep(.arco-btn) { width: 100%; }
.heat-body { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 6px 8px; }
/* 基线 / 对比 两栏,中间 VS 徽标 + 竖向分隔线,日期与 P4 按角色着色 */
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
