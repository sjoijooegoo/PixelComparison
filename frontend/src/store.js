import { defineStore } from 'pinia'
import { api, isRequestCancelled } from './api'
import { router } from './router'
import { logger } from './logger'

export const PAGE_SIZE = 10   // 默认每页条数;实际由对应列表按可用高度动态覆盖
export const MAX_DATE_RANGE_DAYS = 14

// 本地日期 YYYY-MM-DD(避免 toISOString 的时区偏移)
function ymd(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
export function normalizeDateRangeDays(days = 7) {
  const value = Number(days)
  if (!Number.isFinite(value)) return 7
  return Math.max(1, Math.min(MAX_DATE_RANGE_DAYS, Math.trunc(value)))
}

// 连续范围按首尾日期都计入，例如 7月1日～7月14日为14天。
export function inclusiveDateRangeDays(from, to) {
  const parse = (value) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '')
    if (!match) return null
    const [, year, month, day] = match.map(Number)
    const time = Date.UTC(year, month - 1, day)
    const date = new Date(time)
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
      return null
    }
    return time
  }
  const start = parse(from)
  const end = parse(to)
  if (start === null || end === null || end < start) return null
  return Math.floor((end - start) / 86400000) + 1
}

export function isDateRangeAllowed(from, to) {
  const days = inclusiveDateRangeDays(from, to)
  return days !== null && days <= MAX_DATE_RANGE_DAYS
}

// 默认创建时间范围:最近 N 个自然日(N 默认 7,可由项目设置覆盖)
export function defaultDateRange(days = 7) {
  const count = normalizeDateRangeDays(days)
  const today = new Date()
  const from = new Date(today)
  from.setDate(today.getDate() - (count - 1))
  return { created_from: ymd(from), created_to: ymd(today) }
}

// 画质档位选项(与后端 _SHADING_QUALITY_LABELS 一致),高→低
export const SHADING_QUALITY_OPTIONS = [
  { value: 5, label: '电影' },
  { value: 4, label: '极致' },
  { value: 3, label: '精美' },
  { value: 2, label: '均衡' },
  { value: 1, label: '流畅' },
  { value: 0, label: '节能' },
]

// 按项目设置过滤出筛选框画质下拉应显示的档位;空集兜底为全部
export function visibleQualityOptions(settings) {
  const set = new Set(settings?.filter_shading_qualities ?? [5, 4, 3, 2, 1, 0])
  const opts = SHADING_QUALITY_OPTIONS.filter((o) => set.has(o.value))
  return opts.length ? opts : SHADING_QUALITY_OPTIONS
}

// P4 版本号展示:无版本时显示 ——
export function p4Label(v) {
  return (v === null || v === undefined || v === '') ? '——' : `P4 ${v}`
}

export const STATUS_META = {
  fail: { label: '失败', color: 'red' },
  warn: { label: '警告', color: 'orange' },
  pass: { label: '通过', color: 'green' },
  added: { label: '新增', color: 'arcoblue' },
  missing: { label: '缺失', color: 'gray' },
}

// 换向(flip)时单点状态对调:新增↔缺失,其余不变
const REVERSE_STATUS = { added: 'missing', missing: 'added' }
const reverseStatus = (s) => REVERSE_STATUS[s] || s

const GRID_CACHE_LIMIT = 8
const GRID_CACHE_FIELDS = [
  'platform',
  'shading_quality',
  'p4_min',
  'p4_max',
  'created_from',
  'created_to',
  'created_dates',
  'q',
]
const gridCacheState = globalThis.__PIXELCOMP_GRID_CACHE__ ||= {
  cache: new Map(),
  inflight: new Map(),
  epoch: 0,
}
if (!Number.isInteger(gridCacheState.epoch)) gridCacheState.epoch = 0
const gridCache = gridCacheState.cache
const gridInflight = gridCacheState.inflight
const initPromises = new WeakMap()
const requestRuntimes = new WeakMap()
const REQUEST_SEQUENCE_FIELDS = {
  scenes: '_sceneRequestSeq',
  detail: '_detailRequestSeq',
  heatmaps: '_heatmapRequestSeq',
}

function requestRuntime(store, channel) {
  let runtime = requestRuntimes.get(store)
  if (!runtime) {
    runtime = { scenes: { active: null }, detail: { active: null }, heatmaps: { active: null } }
    requestRuntimes.set(store, runtime)
  }
  return runtime[channel]
}

// 每类资源只保留一个有效请求：相同 key 复用 inflight Promise；不同 key 立即取消旧请求。
// requestId 是最终写状态前的第二道保护，兼容服务端已经返回、abort 来不及阻止的情况。
function runLatestRequest(store, channel, key, execute) {
  const runtime = requestRuntime(store, channel)
  if (runtime.active?.key === key) return runtime.active.promise

  runtime.active?.controller.abort()
  const sequenceField = REQUEST_SEQUENCE_FIELDS[channel]
  const requestId = ++store[sequenceField]
  const controller = new AbortController()
  const isLatest = () => store[sequenceField] === requestId
  const operation = Promise.resolve(execute({
    signal: controller.signal,
    requestId,
    isLatest,
  }))
  const active = { key, requestId, controller, promise: null }
  active.promise = operation.then(
    (value) => {
      if (runtime.active?.requestId === requestId) runtime.active = null
      return value
    },
    (error) => {
      if (runtime.active?.requestId === requestId) runtime.active = null
      throw error
    },
  )
  runtime.active = active
  return active.promise
}

function cancelLatestRequest(store, channel) {
  const runtime = requestRuntime(store, channel)
  runtime.active?.controller.abort()
  runtime.active = null
  ++store[REQUEST_SEQUENCE_FIELDS[channel]]
}

function hasActiveRequest(store, channel) {
  return !!requestRuntime(store, channel).active
}

function emptyGrid() {
  return { batches: [], rows: [] }
}

function hasGridParamValue(v) {
  return !(v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length))
}

function gridCacheKey(sceneId, filters) {
  const params = {}
  for (const field of GRID_CACHE_FIELDS) {
    const value = filters[field]
    if (!hasGridParamValue(value)) continue
    params[field] = Array.isArray(value) ? [...value].sort() : value
  }
  return JSON.stringify({ scene_id: sceneId, ...params })
}

function rememberGrid(key, data) {
  gridCache.set(key, data)
  if (gridCache.size > GRID_CACHE_LIMIT) {
    gridCache.delete(gridCache.keys().next().value)
  }
}

function clearGridCache() {
  gridCache.clear()
  gridInflight.clear()
  gridCacheState.epoch += 1
}

function cloneRequestParams(params) {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value]),
  )
}

export const useStore = defineStore('shotdiff', {
  state: () => ({
    meta: {
      scene_ids: [],
      unlisted_scene_ids: [],
      scene_catalog_configured: false,
      show_unlisted_scene_ids: false,
      platforms: [],
      baselines: [],
    },
    filters: { scene_id: '', shading_quality: 5, dateMode: 'range', ...defaultDateRange(), created_dates: [], status: '' },   // 画质默认「电影」(5)

    // 顶部:原始批次列表
    batches: [],
    batchTotal: 0,
    batchPage: 1,
    batchPageSize: PAGE_SIZE,
    batchView: 'list',                 // list(列表) | grid(列表图:同场景多批次图片矩阵)
    grid: { batches: [], rows: [] },   // 批次列表图数据
    initialized: false,                // 首屏最终筛选与数据是否已完成加载
    initializing: false,               // 首屏后台加载中；应用外壳已挂载并展示骨架
    initError: '',                     // 首屏失败原因；页面提供原地重试
    batchLoading: false,
    batchError: '',
    gridLoading: false,
    gridError: '',
    _batchRequestSeq: 0,               // 只允许最新批次请求写回状态
    _gridRequestSeq: 0,                // 只允许最新列表图请求写回状态
    _sceneRequestSeq: 0,               // 对比检查点列表最新请求序号
    _detailRequestSeq: 0,              // 检查点详情最新请求序号
    _heatmapRequestSeq: 0,             // 列表图热力图 lookup 最新请求序号
    gridCollapsed: new Set(),          // 列表图已折叠的批次列(按批次 id;跨刷新/切场景保留)
    gridHeatmaps: null,                // 列表图热力图列:{ current_id, baseline_id, exists, map:{scene_name:url} };只读命中缓存,不触发计算
    gridHeatmapLoading: false,
    gridHeatmapError: '',
    uploadVisible: false,              // 手动上报弹窗(由顶栏按钮触发)
    // 对比的两侧选择(角色);currentBatch/baselineBatch 是「当前场景」的激活镜像
    currentBatch: null,   // 对比批次(待检查)
    baselineBatch: null,  // 基线批次(参照)
    rolesByScene: {},     // 按场景记忆的选择 { sceneId: { baseline, current } };切场景保留、切回即恢复

    // 历史对比列表(对比结果页左侧)
    comparisons: [],
    // 运行后的活动对比
    selectedComparison: null,
    flip: false,          // 结果页换向:true 时把当前对比按"基线↔对比"翻转展示
    running: false,
    progress: { done: 0, total: 0 },   // 后台对比进度

    sceneSearch: '',
    page: 1,
    pageSize: PAGE_SIZE,   // 由 SceneList 按列表区可用高度动态设置
    scenes: [],
    sceneTotal: 0,
    counts: { all: 0, fail: 0, warn: 0, pass: 0, added: 0, missing: 0 },
    sceneSort: 'name',   // name(场景名) | diff(差异率降序)
    sceneError: '',

    detail: null,        // /api/items/{id} 响应
    selectedSceneItemId: null,
    detailLoading: false,
    detailError: '',
    comparisonDataStale: false,        // 请求中离开结果页后，重新进入需恢复列表/详情
    viewMode: 'tri',     // tri(三视图) | slide(滑动对比)
    loading: false,

    // 对比算法配置(项目设置页可改);默认与后端 DEFAULT_SETTINGS 一致
    settings: {
      pixel_diff_threshold: 8,
      fail_threshold: 2.0,
      warn_threshold: 0.3,
      heatmap_blur: 6,
      heatmap_sensitivity: 0.25,
      heatmap_method: 'enhanced',   // enhanced=绝对幅度+gamma+密度门控;legacy=旧峰值归一化
      heatmap_norm_scale: 80.0,
      heatmap_gamma: 1.4,
      heatmap_density_radius: 16.0,
      heatmap_density_floor: 0.2,
      default_shading_quality: 5,   // 筛选默认画质;-1 表示「全部画质」
      default_date_range_days: 7,   // 筛选默认日期范围:最近 N 天
      filter_shading_qualities: [5, 4, 3, 2, 1, 0],   // 筛选框画质下拉显示哪几档
      scene_id_order: null,         // 外部模块下发的权威场景目录；只读展示，不由设置页修改
      show_unlisted_scene_ids: false, // 是否把目录外、数据库中已有的场景追加到筛选框
    },
  }),

  getters: {
    canCompare: (s) =>
      !!(s.currentBatch && s.baselineBatch && s.currentBatch.id !== s.baselineBatch.id),

    // 下发给接口的筛选:按日期模式只带对应日期键(范围 / 指定多天),互不混用
    requestFilters: (s) => {
      const { dateMode, created_from, created_to, created_dates, ...rest } = s.filters
      if (dateMode === 'days') return { ...rest, created_dates }
      return { ...rest, created_from, created_to }
    },

    hasEmptyDateSelection: (s) =>
      s.filters.dateMode === 'days' && !s.filters.created_dates.length,

    // ---- 换向展示:flip=true 时把规范方向的数据按"基线↔对比"翻转 ----
    // 当前检查点详情(三视图/指标面板用):对调当前/基线图、状态、直方图
    orientedDetail: (s) => {
      const d = s.detail
      if (!d || !s.flip) return d
      const m = d.metrics
      return {
        ...d,
        current_url: d.baseline_url,
        baseline_url: d.current_url,
        status: reverseStatus(d.status),
        metrics: m ? { ...m, hist_current: m.hist_baseline, hist_baseline: m.hist_current } : m,
      }
    },

    // 检查点缩略图列表:翻转时缩略图取另一侧
    orientedScenes: (s) =>
      s.flip
        ? s.scenes.map((it) => ({ ...it, thumb_url: it.baseline_url || it.current_url }))
        : s.scenes,

    // 状态计数:翻转时新增↔缺失对调
    orientedCounts: (s) => {
      const c = s.counts
      if (!s.flip) return c
      return { ...c, added: c.missing, missing: c.added }
    },

    // 对比对(摘要头部):翻转时对调两侧批次信息,整体状态按对调后的计数推算
    orientedComparison: (s) => {
      const c = s.selectedComparison
      if (!c) return c
      if (!s.flip) return c
      const cn = s.counts
      const status = (cn.fail || cn.added) ? 'fail' : (cn.warn || cn.missing) ? 'warn' : 'pass'
      return {
        ...c,
        status,
        batch_id: c.ref_batch_id,
        ref_batch_id: c.batch_id,
        p4_version: c.ref_p4_version,
        ref_p4_version: c.p4_version,
        shading_quality_label: c.ref_shading_quality_label,
        ref_shading_quality_label: c.shading_quality_label,
        batch_created_at: c.ref_created_at,
        ref_created_at: c.batch_created_at,
        ref_label: `#${c.batch_id}`,   // 翻转后参照=原对比批次(不一定是已晋升基线)
      }
    },
  },

  actions: {
    async init(routeSceneId = '') {
      const active = initPromises.get(this)
      if (active) return await active
      const initialization = this._initialize(routeSceneId)
      initPromises.set(this, initialization)
      try {
        return await initialization
      } finally {
        if (initPromises.get(this) === initialization) initPromises.delete(this)
      }
    },

    async _initialize(routeSceneId = '') {
      this.initialized = false
      this.initializing = true
      this.initError = ''
      const sid = Array.isArray(routeSceneId) ? routeSceneId[0] : routeSceneId
      // 必须在任何 await 之前固定深链场景；即使初始化接口失败，挂载后的兜底请求
      // 也不会先发出未带 scene_id 的全局查询。
      if (sid) {
        this.filters.scene_id = sid
        this.batchView = 'grid'
      } else {
        this.filters.scene_id = ''
        this.batchView = 'list'
      }
      try {
        // 两个配置接口互不依赖，并行请求少等一个网络往返；批次请求仍要等最终筛选确定。
        await Promise.all([this.loadMeta(), this.loadSettings()])
        const acceptedSid = sid && this.meta.scene_ids.includes(sid) ? sid : ''
        this.filters = this.defaultFilters()   // 用项目设置里的默认画质/日期范围初始化筛选
        if (acceptedSid) this.filters.scene_id = acceptedSid
        this.batchView = acceptedSid ? 'grid' : 'list'
        this.batchPage = 1
        const loads = [this.loadBatches()]
        if (acceptedSid) loads.push(this.loadGrid())
        await Promise.all(loads)
        this.initialized = true
      } catch (error) {
        this.initialized = false
        this.initError = error?.message || '初始化失败，请重试'
        throw error
      } finally {
        this.initializing = false
      }
    },

    // 由项目设置算出的整套默认筛选(首次进入 / 点「清空」时套用)
    defaultFilters() {
      const q = this.settings.default_shading_quality
      return {
        scene_id: '',
        shading_quality: (q === -1 || q == null) ? '' : q,   // -1/空 → 全部画质
        dateMode: 'range',
        ...defaultDateRange(this.settings.default_date_range_days ?? 7),
        created_dates: [],
        status: '',
      }
    },

    // 筛选器选项(场景/平台/基线):随批次实时去重,刷新时一并更新
    async loadMeta() {
      const next = await api.meta()
      this.meta = {
        unlisted_scene_ids: [],
        scene_catalog_configured: false,
        show_unlisted_scene_ids: false,
        ...next,
      }
      const currentSceneId = this.filters.scene_id
      if (currentSceneId && !this.meta.scene_ids.includes(currentSceneId)) {
        this.filters.scene_id = ''
        this.batchPage = 1
        this.batchView = 'list'
        this.grid = emptyGrid()
        this.gridHeatmaps = null
        return currentSceneId
      }
      return ''
    },

    async loadSettings() {
      this.settings = await api.settings()
    },

    async saveSettings(patch) {
      this.settings = await api.saveSettings(patch)
    },

    // 切到某场景时,把激活的选择切换为该场景记忆的选择(无则置空)。
    // 仅在选定了场景、且当前激活的不是该场景时才动;同场景内换页/改日期为 no-op。
    syncRolesForScene() {
      const sid = this.filters.scene_id
      if (!sid) return
      const activeScene = this.baselineBatch?.scene_id || this.currentBatch?.scene_id
      if (activeScene === sid) return
      const saved = this.rolesByScene[sid]
      this.baselineBatch = saved?.baseline || null
      this.currentBatch = saved?.current || null
    },

    async loadBatches() {
      const requestId = ++this._batchRequestSeq
      this.batchLoading = true
      this.batchError = ''
      // 批次筛选变化后，任何仍在途的列表图响应也已经过期；配套的 loadGrid
      // 会取得新的序号。这样清空筛选/空日期时不会短暂回写旧矩阵。
      ++this._gridRequestSeq
      this.syncRolesForScene()
      if (this.hasEmptyDateSelection) {
        this.batches = []
        this.batchTotal = 0
        this.batchLoading = false
        return
      }
      const params = cloneRequestParams({
        ...this.requestFilters,
        page: this.batchPage,
        page_size: this.batchPageSize,
      })
      let result
      try {
        result = await api.batches(params)
      } catch (error) {
        if (requestId !== this._batchRequestSeq) return null
        this.batchError = error?.message || '批次列表加载失败'
        throw error
      } finally {
        if (requestId === this._batchRequestSeq) this.batchLoading = false
      }
      if (requestId !== this._batchRequestSeq) return null
      const { items, total } = result
      this.batches = items
      this.batchTotal = total
      return result
    },

    // 刷新批次(筛选项 + 列表 + 列表图)
    async refreshBatches() {
      ++this._batchRequestSeq
      ++this._gridRequestSeq
      clearGridCache()
      const hiddenSceneId = await this.loadMeta()
      const loads = [this.loadBatches()]
      if (this.batchView === 'grid') loads.push(this.loadGrid())
      await Promise.all(loads)
      return hiddenSceneId
    },

    // 删除单个批次(级联删其对比/对比项/基线/图片/热力图/缩略图);清理本地选择并刷新
    async deleteBatch(id) {
      await api.deleteBatch(id)
      if (this.currentBatch?.id === id) this.currentBatch = null
      if (this.baselineBatch?.id === id) this.baselineBatch = null
      for (const k of Object.keys(this.rolesByScene)) {
        const r = this.rolesByScene[k]
        if (r.baseline?.id === id) r.baseline = null
        if (r.current?.id === id) r.current = null
      }
      await this.refreshBatches()
    },

    // 批次列表图:同场景多批次的图片矩阵(需先选场景)
    async loadGrid() {
      const requestId = ++this._gridRequestSeq
      this.gridLoading = true
      this.gridError = ''
      try {
        if (!this.filters.scene_id) { this.grid = emptyGrid(); return }
        if (this.hasEmptyDateSelection) {
          this.grid = emptyGrid()
          this._clearRolesOutsideGrid(this.filters.scene_id)
          return
        }
        // 传全部筛选(scene_id 在路径里,多余的 status 等会被后端忽略)
        const sceneId = this.filters.scene_id
        const filters = cloneRequestParams(this.requestFilters)
        const key = gridCacheKey(sceneId, filters)
        if (gridCache.has(key)) {
          if (requestId !== this._gridRequestSeq) return null
          this.grid = gridCache.get(key)
          this._clearRolesOutsideGrid(sceneId)
          this.loadGridHeatmaps()
          return this.grid
        }
        if (!gridInflight.has(key)) {
          const requestEpoch = gridCacheState.epoch
          const request = api.sceneGrid(sceneId, filters)
            .then((data) => {
              if (gridCacheState.epoch === requestEpoch) rememberGrid(key, data)
              return data
            })
            .finally(() => {
              // clearGridCache 后同 key 可能已有一条新请求；旧请求不得误删新请求。
              if (gridInflight.get(key) === request) gridInflight.delete(key)
            })
          gridInflight.set(key, request)
        }
        const data = await gridInflight.get(key)
        if (requestId !== this._gridRequestSeq) return null
        if (gridCacheKey(this.filters.scene_id, this.requestFilters) !== key) return null
        this.grid = data
        this._clearRolesOutsideGrid(sceneId)
        this.loadGridHeatmaps()
        return data
      } catch (error) {
        if (requestId !== this._gridRequestSeq) return null
        this.gridError = error?.message || '列表图加载失败'
        throw error
      } finally {
        if (requestId === this._gridRequestSeq) this.gridLoading = false
      }
    },

    // 筛选项变化后,已选基线/对比若不在当前列表图列里,就清掉;
    // 避免用户看不到高亮列,但状态里仍残留一个被筛选隐藏的批次。
    _clearRolesOutsideGrid(scene) {
      if (!scene) return
      const visibleIds = new Set(this.grid.batches.map((b) => String(b.id)))
      let changed = false
      if (this.baselineBatch && !visibleIds.has(String(this.baselineBatch.id))) {
        this.baselineBatch = null
        changed = true
      }
      if (this.currentBatch && !visibleIds.has(String(this.currentBatch.id))) {
        this.currentBatch = null
        changed = true
      }
      if (changed) this._saveRoles(scene)
    },

    // 把当前激活的选择写入按场景记忆表(都为空则删除该场景条目)
    _saveRoles(scene) {
      if (!scene) return
      if (this.baselineBatch || this.currentBatch) {
        this.rolesByScene[scene] = { baseline: this.baselineBatch, current: this.currentBatch }
      } else {
        delete this.rolesByScene[scene]
      }
    },

    // role: 'current'(对比) | 'baseline'(基线)
    setRole(batch, role) {
      const other = role === 'current' ? this.baselineBatch : this.currentBatch
      // 取消同一批次的另一角色,避免自比
      if (other && other.id === batch.id) {
        if (role === 'current') this.baselineBatch = null
        else this.currentBatch = null
      }
      if (role === 'current') this.currentBatch = batch
      else this.baselineBatch = batch
      this._saveRoles(batch.scene_id)
      this.loadGridHeatmaps()
    },

    clearRole(role) {
      const scene = this.currentBatch?.scene_id || this.baselineBatch?.scene_id || this.filters.scene_id
      if (role === 'current') this.currentBatch = null
      else this.baselineBatch = null
      this._saveRoles(scene)
      this.loadGridHeatmaps()
    },

    // 列表图热力图列:两侧都选且都属于当前场景列表图时,只读查找已有对比的各检查点热力图;
    // 命中缓存即填充,未对比过则 exists=false(留空提示),绝不触发计算。
    async loadGridHeatmaps() {
      const cur = this.currentBatch
      const base = this.baselineBatch
      const inGrid = (b) => b && this.grid.batches.some((x) => x.id === b.id)
      if (!cur || !base || cur.id === base.id || !inGrid(cur) || !inGrid(base)) {
        cancelLatestRequest(this, 'heatmaps')
        this.gridHeatmaps = null
        this.gridHeatmapLoading = false
        this.gridHeatmapError = ''
        return
      }
      const key = `${cur.id}|${base.id}`
      return runLatestRequest(this, 'heatmaps', key, async ({ signal, isLatest }) => {
        this.gridHeatmapLoading = true
        this.gridHeatmapError = ''
        try {
          const res = await api.comparisonLookup(cur.id, base.id, { signal })
          // 序号 + 当前角色双重校验，旧请求即使在 abort 前已完成也不能回写。
          if (!isLatest()) return null
          if (this.currentBatch?.id !== cur.id || this.baselineBatch?.id !== base.id) return null
          this.gridHeatmaps = {
            current_id: cur.id,
            baseline_id: base.id,
            exists: !!res.exists,
            map: res.heatmaps || {},
            comparison: res.comparison || null,   // 列头「差异对比」点击跳转需要 id/方向
          }
          return this.gridHeatmaps
        } catch (error) {
          if (isRequestCancelled(error) || !isLatest()) return null
          this.gridHeatmapError = error?.message || '热力图查询失败'
          this.gridHeatmaps = null
          return null
        } finally {
          if (isLatest()) this.gridHeatmapLoading = false
        }
      })
    },

    cancelGridHeatmapRequest() {
      cancelLatestRequest(this, 'heatmaps')
      this.gridHeatmapLoading = false
    },

    // 列表图列头「差异对比」点击:跳到该对批次的对比结果页(/comparison/:id)
    gotoGridComparison() {
      const h = this.gridHeatmaps
      if (!h?.exists || !h.comparison) return
      // 库内规范方向:batch_id=对比侧、ref_batch_id=基线侧;与当前网格所选对比侧不一致则翻转展示
      const flip = String(h.comparison.batch_id) !== String(this.currentBatch?.id)
      router.push({ path: `/comparison/${h.comparison.id}`, query: flip ? { flip: '1' } : undefined })
    },

    // 按 id 打开对比(深链/列头跳转用);在已加载历史中查找,缺失再拉一次,仍无则返回 false
    async openComparisonById(id, flip = false) {
      let c = this.comparisons.find((x) => String(x.id) === String(id))
      if (!c) {
        await this.loadComparisons()
        c = this.comparisons.find((x) => String(x.id) === String(id))
      }
      if (!c) return false
      await this.openComparison(c, flip)
      return true
    },

    async loadComparisons() {
      // 对比历史不随批次页筛选(尤其场景ID)过滤,始终加载全部(后端保留近 14 天)
      const { items } = await api.comparisons({})
      this.comparisons = items
    },

    // 发起对比 -> 命中缓存直接返回;否则轮询后台任务进度直到完成
    // 返回 { comparison, flip }:flip 表示库内方向与请求相反(由前端翻转展示)
    async _awaitComparison(body) {
      this.progress = { done: 0, total: 0 }
      const res = await api.createComparison(body)
      const flip = !!res.flip
      if (res.status === 'done' && res.comparison) return { comparison: res.comparison, flip }
      while (true) {
        await new Promise((r) => setTimeout(r, 400))
        const t = await api.comparisonTask(res.task_id)
        this.progress = { done: t.done, total: t.total }
        if (t.status === 'done') return { comparison: t.comparison, flip }
        if (t.status === 'error') throw new Error(t.error || '对比失败')
      }
    },

    async runComparison() {
      if (!this.canCompare) return
      this.running = true
      logger.info('发起对比', `#${this.baselineBatch.id} vs #${this.currentBatch.id}`)
      try {
        const { comparison, flip } = await this._awaitComparison({
          batch_id: this.currentBatch.id,
          ref_batch_id: this.baselineBatch.id,
        })
        await this.openComparison(comparison, flip)
        await this.loadComparisons()   // 刷新历史(可能新增了一条)
        this.loadGridHeatmaps()        // 新对比已生成,列表图热力图列可直接命中
        // 列表图里发起对比后留在原页(热力图列就地填充);列表视图仍跳到结果页
        if (this.batchView !== 'grid') router.push('/comparison')
        return comparison
      } finally {
        this.running = false
        this.progress = { done: 0, total: 0 }
      }
    },

    // 强制重算当前对比(批次截图变更等场景);沿用当前查看方向(flip)
    async rerunComparison() {
      const c = this.selectedComparison
      if (!c) return
      const flip = this.flip
      this.running = true
      try {
        const { comparison } = await this._awaitComparison({
          batch_id: c.batch_id,
          ref_batch_id: c.ref_batch_id,
          force: true,
        })
        await this.openComparison(comparison, flip)
        await this.loadComparisons()
        this.loadGridHeatmaps()        // 重算后热力图已更新,刷新列表图热力图列
        return comparison
      } finally {
        this.running = false
        this.progress = { done: 0, total: 0 }
      }
    },

    // 结果页换向:纯展示翻转(数据已含两侧),零网络
    async swapComparison() {
      if (!this.selectedComparison) return
      this.flip = !this.flip
    },

    async openComparison(comparison, flip = false) {
      this.comparisonDataStale = false
      this.selectedComparison = comparison
      this.flip = flip
      this.page = 1
      this.sceneSearch = ''
      this.sceneSort = 'name'
      this.scenes = []
      this.detail = null
      this.selectedSceneItemId = null
      cancelLatestRequest(this, 'detail')
      this.detailLoading = false
      this.detailError = ''
      const comparisonId = comparison.id
      const data = await this.loadScenes()
      if (!data || this.selectedComparison?.id !== comparisonId) return
      if (data.items.length) await this.selectScene(data.items[0].id)
      else this.detail = null
    },

    async toggleSceneSort() {
      this.sceneSort = this.sceneSort === 'diff' ? 'name' : 'diff'
      this.page = 1
      await this.loadScenes()
    },

    async loadScenes() {
      if (!this.selectedComparison) {
        cancelLatestRequest(this, 'scenes')
        this.loading = false
        return null
      }
      const comparisonId = this.selectedComparison.id
      const params = cloneRequestParams({
        q: this.sceneSearch,
        sort: this.sceneSort,
        page: this.page,
        page_size: this.pageSize,
      })
      const key = JSON.stringify({ comparisonId, ...params })
      return runLatestRequest(this, 'scenes', key, async ({ signal, isLatest }) => {
        this.loading = true
        this.sceneError = ''
        try {
          const data = await api.scenes(comparisonId, params, { signal })
          if (!isLatest() || this.selectedComparison?.id !== comparisonId) return null
          this.scenes = data.items
          this.sceneTotal = data.total
          this.counts = data.counts
          return data
        } catch (error) {
          if (isRequestCancelled(error) || !isLatest()) return null
          this.sceneError = error?.message || '检查点列表加载失败'
          return null
        } finally {
          if (isLatest()) this.loading = false
        }
      })
    },

    async selectScene(id) {
      if (id === null || id === undefined || id === '') {
        cancelLatestRequest(this, 'detail')
        this.selectedSceneItemId = null
        this.detail = null
        this.detailLoading = false
        this.detailError = ''
        return null
      }
      const key = String(id)
      const runtime = requestRuntime(this, 'detail')
      if (runtime.active?.key !== key) {
        this.selectedSceneItemId = id
        this.detail = null
      }
      return runLatestRequest(this, 'detail', key, async ({ signal, isLatest }) => {
        this.detailLoading = true
        this.detailError = ''
        try {
          const data = await api.item(id, { signal })
          if (!isLatest() || String(this.selectedSceneItemId) !== key) return null
          this.detail = data
          return data
        } catch (error) {
          if (isRequestCancelled(error) || !isLatest()) return null
          this.detailError = error?.message || '检查点详情加载失败'
          return null
        } finally {
          if (isLatest()) this.detailLoading = false
        }
      })
    },

    async gotoPrev() {
      if (this.detail?.prev_id) await this.selectScene(this.detail.prev_id)
    },
    async gotoNext() {
      if (this.detail?.next_id) await this.selectScene(this.detail.next_id)
    },

    cancelComparisonDataRequests() {
      const interrupted = hasActiveRequest(this, 'scenes') || hasActiveRequest(this, 'detail')
      cancelLatestRequest(this, 'scenes')
      cancelLatestRequest(this, 'detail')
      this.loading = false
      this.detailLoading = false
      if (interrupted) this.comparisonDataStale = true
    },

    async resumeComparisonData() {
      if (!this.comparisonDataStale || !this.selectedComparison) return null
      return await this.openComparison(this.selectedComparison, this.flip)
    },
  },
})
