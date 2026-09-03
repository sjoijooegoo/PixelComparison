// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const apiMock = vi.hoisted(() => ({
  mapBuildMeta: vi.fn(),
  mapBuildOverview: vi.fn(),
  mapBuildTrend: vi.fn(),
}))
const storeMock = vi.hoisted(() => ({
  initialized: true,
  meta: {
    branch_tags: ['main', 'engine-ue5'],
    scene_ids: ['Forest_WP', 'Coral_WP', 'Unlisted_WP'],
    unlisted_scene_ids: ['Unlisted_WP'],
  },
  filters: { branch_tag: 'main' },
  init: vi.fn(),
}))
const routeMock = vi.hoisted(() => ({
  path: '/map-build', params: { sceneId: undefined }, query: {},
}))
const routerMock = vi.hoisted(() => ({ replace: vi.fn() }))

vi.mock('../api', () => ({
  api: apiMock,
  isRequestCancelled: (error) => error?.code === 'ABORTED',
}))
vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))
vi.mock('../store', () => ({
  p4Label: (value) => `P4 ${value}`,
}))
vi.mock('../stores/projectStore', () => ({ useProjectStore: () => storeMock }))
vi.mock('../components/MapBuildTrendChart.vue', () => ({
  default: defineComponent({
    props: {
      points: { type: Array, default: () => [] },
      currentBatchId: { type: [String, Number], default: '' },
    },
    emits: ['selectBatch'],
    template: '<div class="trend-stub">{{ points.length }} points</div>',
  }),
}))

import MapBuildView from './MapBuildView.vue'
import MapBuildAtlas from '../components/MapBuildAtlas.vue'
import MapBuildDetailPanel from '../components/MapBuildDetailPanel.vue'
import mapBuildViewSource from './MapBuildView.vue?raw'
import mapBuildAtlasSource from '../components/MapBuildAtlas.vue?raw'
import { runPageRefresh } from '../pageActions'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

const meta = {
  scene_ids: [{
    value: 'Coral_WP', batch_count: 2, latest_at: '2026-08-05T10:00',
    platforms: ['Windows'], shading_qualities: [{ value: 5, label: '电影' }],
  }],
  platforms: ['Windows'],
  shading_qualities: [{ value: 5, label: '电影' }],
}
const batch = (id, date) => ({
  id, scene_id: 'Coral_WP', p4_version: Number(id), platform: 'Windows',
  shading_quality: 5, shading_quality_label: '电影', created_at: date,
})
const metrics = (total) => ({
  total_bytes: total,
  lightmap_bytes: total / 2,
  hue_bytes: total / 10,
  shadowmap_bytes: total / 4,
  all_mips_bytes: total * 2,
  cook_estimate_bytes: total * 3,
  texture_count: 1,
  lightmap_all_mips_bytes: total / 2,
  shadowmap_all_mips_bytes: total / 4,
  hue_all_mips_bytes: total / 10,
  precomputed_light_volume_bytes: total / 5,
  precomputed_reflection_volume_bytes: total / 6,
  volumetric_lightmap_bytes: total / 7,
  reflection_capture_bytes: total / 8,
  mesh_map_build_data_bytes: total / 9,
  light_build_data_bytes: total / 10,
  precomputed_instanced_ilc_bytes: total / 11,
  precomputed_instanced_pr_bytes: total / 12,
  lightmap_resource_cluster_bytes: total / 13,
})
const reflectionMetrics = {
  ...metrics(12 * 1024 * 1024),
  all_mips_bytes: 12 * 1024 * 1024,
  cook_estimate_bytes: 12 * 1024 * 1024,
  texture_count: 0,
}
const overview = {
  batch: batch('2', '2026-08-05T10:00'),
  batch_window: { start_date: '2026-07-07', end_date: '2026-08-05' },
  available_batches: [batch('2', '2026-08-05T10:00'), batch('1', '2026-08-04T10:00')],
  world: {
    label: '主分块', path: '/root', has_children: true,
    metrics: metrics(200), self_metrics: metrics(20), subtree_metrics: metrics(200),
  },
  blocks: [{
    index: 3,
    label: '分块 3',
    path: '/block3',
    has_children: true,
    metrics: metrics(180),
    self_metrics: metrics(30),
    subtree_metrics: metrics(180),
    sub_blocks: [
      {
        index: 0, label: '0x00', path: '/0', has_children: false,
        metrics: metrics(80), self_metrics: metrics(80), subtree_metrics: metrics(80),
      },
      {
        index: 1, label: '0x01', path: '/1', has_children: false,
        metrics: metrics(100), self_metrics: metrics(100), subtree_metrics: metrics(100),
      },
    ],
  }],
  auxiliary_blocks: [{
    key: '/reflection',
    label: '反射分块',
    path: '/reflection',
    has_children: false,
    metrics: reflectionMetrics,
    self_metrics: reflectionMetrics,
    subtree_metrics: reflectionMetrics,
  }],
}
const overviewWithoutBlocks = {
  ...overview,
  world: {
    ...overview.world,
    has_children: false,
    self_metrics: metrics(20),
    subtree_metrics: metrics(20),
  },
  blocks: [],
  auxiliary_blocks: [],
}
function overviewWithComparison() {
  const orderedBatches = [
    batch('3', '2026-08-06T09:30'),
    batch('2', '2026-08-05T10:00'),
    batch('1', '2026-07-29T09:30'),
    batch('0', '2026-07-20T09:30'),
  ]
  return {
    ...overview,
    available_batches: orderedBatches,
    comparison: {
      selection: 'previous',
      batch: batch('1', '2026-07-29T09:30'),
      default_batch: batch('1', '2026-07-29T09:30'),
      available_batches: orderedBatches,
    },
    world: {
      ...overview.world,
      comparison_metrics: { self: metrics(10), subtree: metrics(100) },
    },
    blocks: overview.blocks.map((block) => ({
      ...block,
      comparison_metrics: { self: metrics(15), subtree: metrics(90) },
      sub_blocks: block.sub_blocks.map((cell) => ({
        ...cell,
        comparison_metrics: { self: metrics(cell.index === 0 ? 40 : 50), subtree: metrics(cell.index === 0 ? 40 : 50) },
      })),
    })),
    auxiliary_blocks: overview.auxiliary_blocks.map((block) => ({
      ...block,
      comparison_metrics: { self: metrics(6 * 1024 * 1024), subtree: metrics(6 * 1024 * 1024) },
    })),
  }
}
const worldTrend = {
  selection: { scope: 'main_block', metric_scope: 'self', label: '主分块 · 自身数据' },
  points: [{ batch: batch('1', '2026-08-04T10:00'), metrics: metrics(100) }],
  window: { days: 30, start_date: '2026-07-07', end_date: '2026-08-05', truncated: false },
}
const defaultTrendRange = { start_date: '2026-07-07', end_date: '2026-08-05' }

const SlotStub = defineComponent({ template: '<div><slot/></div>' })
const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<div class="select-stub"><slot/></div>',
})
const RangePickerStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<div class="range-picker-stub" />',
})

function mountView() {
  return mount(MapBuildView, {
    global: {
      stubs: {
        'a-select': SelectStub,
        'a-range-picker': RangePickerStub,
        'a-option': SlotStub,
        'a-tooltip': SlotStub,
        'a-alert': SlotStub,
        'a-spin': SlotStub,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  storeMock.initialized = true
  storeMock.meta.branch_tags = ['main', 'engine-ue5']
  storeMock.init.mockResolvedValue()
  routeMock.path = '/map-build'
  routeMock.params.sceneId = undefined
  routeMock.query = {}
  storeMock.filters.branch_tag = 'main'
  routerMock.replace.mockResolvedValue()
  apiMock.mapBuildMeta.mockResolvedValue(meta)
  apiMock.mapBuildOverview.mockResolvedValue(overview)
  apiMock.mapBuildTrend.mockResolvedValue(worldTrend)
})

describe('MapBuildView', () => {
  it('筛选栏按场景、时间、基线和对比的操作顺序紧凑排列', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findAll('.toolbar .filter-field .label').map((item) => item.text())).toEqual([
      '分支', '场景ID', '创建时间', '基线批次', '对比批次',
    ])
    expect(mapBuildViewSource).toContain('.batch-field :deep(.batch-select),')
    expect(mapBuildViewSource).toContain('.compare-field { flex: 1 1 222px; max-width: 410px; }')
    expect(mapBuildViewSource).toContain('width: 168px; min-width: 168px; flex: 1 1 168px;')
    expect(mapBuildViewSource).toContain('.batch-date-field :deep(.batch-date-picker) { width: 240px; }')
  })

  it('基线批次使用 P4 和采集时间展示并标记最新项', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('.batch-select').attributes('allow-search')).toBeDefined()
    expect(wrapper.get('.batch-select').text()).toContain(
      'P4 2 · 2026-08-05 10:00（最新）',
    )
    expect(wrapper.get('.batch-select').text()).toContain(
      'P4 1 · 2026-08-04 10:00',
    )
    expect(wrapper.get('.batch-select').text()).not.toContain('#2')
    expect(wrapper.get('.batch-select').text()).not.toContain('P4 1（最新）')
  })

  it('批次日历默认展示 30 天并由批次列表和数据趋势共用', async () => {
    const wrapper = mountView()
    await flushPromises()

    const rangePicker = wrapper.findComponent('.batch-date-picker')
    expect(rangePicker.props('modelValue')).toEqual(['2026-07-07', '2026-08-05'])
    expect(rangePicker.attributes('value-format')).toBe('YYYY-MM-DD')
    expect(rangePicker.attributes('allow-clear')).toBeDefined()
    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      ...defaultTrendRange,
      metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    const rollingLocation = routerMock.replace.mock.calls.at(-1)[0]
    expect(rollingLocation.query).toMatchObject({
      branch_tag: 'main', range_mode: 'rolling',
    })
    expect(rollingLocation.query).not.toHaveProperty('from')
    expect(rollingLocation.query).not.toHaveProperty('to')
    expect(wrapper.find('.days-select').exists()).toBe(false)
    expect(wrapper.find('.custom-range-picker').exists()).toBe(false)

    vi.clearAllMocks()
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: batch('1', '2026-08-01T10:00'),
      batch_window: { start_date: '2026-07-01', end_date: '2026-08-01' },
      available_batches: [batch('1', '2026-08-01T10:00')],
      comparison: {
        selection: 'off',
        batch: null,
        default_batch: null,
        available_batches: [batch('1', '2026-08-01T10:00')],
      },
    })
    await rangePicker.vm.$emit('change', ['2026-07-01', '2026-08-01'])
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      batch_start: '2026-07-01',
      batch_end: '2026-08-01',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      start_date: '2026-07-01',
      end_date: '2026-08-01',
      metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.get('.batch-select').text()).not.toContain('P4 2')
    expect(wrapper.get('.compare-select').text()).not.toContain('P4 2')
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      query: expect.objectContaining({
        range_mode: 'fixed',
        from: '2026-07-01',
        to: '2026-08-01',
      }),
    }))
  })

  it('批次日历最多接受包含首尾日期的 60 天', async () => {
    const wrapper = mountView()
    await flushPromises()
    const rangePicker = wrapper.findComponent('.batch-date-picker')
    vi.clearAllMocks()

    await rangePicker.vm.$emit('change', ['2026-06-01', '2026-08-05'])
    await flushPromises()

    expect(wrapper.text()).toContain('创建时间范围最多选择 60 天')
    expect(rangePicker.props('modelValue')).toEqual(['2026-07-07', '2026-08-05'])
    expect(apiMock.mapBuildOverview).not.toHaveBeenCalled()
    expect(apiMock.mapBuildTrend).not.toHaveBeenCalled()
  })

  it('刷新批次日期 URL 后恢复日历并请求对应时间范围', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = {
      range_mode: 'fixed', from: '2026-07-01', to: '2026-08-01',
    }
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch_window: { start_date: '2026-07-01', end_date: '2026-08-01' },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent('.batch-date-picker').props('modelValue')).toEqual([
      '2026-07-01',
      '2026-08-01',
    ])
    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      batch_start: '2026-07-01',
      batch_end: '2026-08-01',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      start_date: '2026-07-01',
      end_date: '2026-08-01',
      metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('没有 fixed 语义的旧绝对日期 URL 会恢复为滚动 30 天', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = { from: '2026-08-13', to: '2026-08-20', compare: 'off' }

    mountView()
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    const location = routerMock.replace.mock.calls.at(-1)[0]
    expect(location.query.range_mode).toBe('rolling')
    expect(location.query).not.toHaveProperty('from')
    expect(location.query).not.toHaveProperty('to')
  })

  it('创建时间范围没有数据时清空批次选择和旧页面', async () => {
    const wrapper = mountView()
    await flushPromises()
    vi.clearAllMocks()
    const noData = Object.assign(new Error('当前筛选没有烘培数据'), { status: 404 })
    apiMock.mapBuildOverview.mockRejectedValueOnce(noData)

    await wrapper.findComponent('.batch-date-picker').vm.$emit(
      'change',
      ['2026-01-01', '2026-01-31'],
    )
    await flushPromises()

    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('')
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('')
    expect(wrapper.get('.date-range-empty').text()).toContain('当前时间范围没有烘培数据')
    expect(wrapper.find('.atlas-row').exists()).toBe(false)
    expect(wrapper.find('.trend-card').exists()).toBe(false)
    expect(apiMock.mapBuildTrend).not.toHaveBeenCalled()
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Coral_WP',
      query: {
        branch_tag: 'main',
        range_mode: 'fixed',
        from: '2026-01-01',
        to: '2026-01-31',
      },
    })
  })

  it('分块与指标明细使用同一历史批次展示变化率', async () => {
    apiMock.mapBuildOverview.mockResolvedValueOnce(overviewWithComparison())

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('previous')
    expect(wrapper.get('.compare-select').text()).toContain('P4 1 · 2026-07-29 09:30')
    expect(wrapper.get('.compare-select').text()).toContain('P4 3 · 2026-08-06 09:30')
    expect(wrapper.get('.compare-select').text()).toContain(
      'P4 2 · 2026-08-05 10:00（当前基线）',
    )
    expect(wrapper.get('.compare-select').text()).not.toContain('上一个批次')
    const baselineText = wrapper.get('.batch-select').text()
    const comparisonText = wrapper.get('.compare-select').text()
    for (const [left, right] of [['P4 3', 'P4 2'], ['P4 2', 'P4 1'], ['P4 1', 'P4 0']]) {
      expect(baselineText.indexOf(left)).toBeLessThan(baselineText.indexOf(right))
      expect(comparisonText.indexOf(left)).toBeLessThan(comparisonText.indexOf(right))
    }
    const currentBaselineOption = wrapper.findAll('.compare-select > div')
      .find((node) => node.text().includes('当前基线'))
    expect(currentBaselineOption?.attributes('disabled')).toBeDefined()
    expect(wrapper.get('.compare-field').attributes('title')).toBeUndefined()
    expect(wrapper.get('.world-total .metric-delta').attributes('aria-label')).toBe('100.0% ↑')
    expect(wrapper.get('.world-total .metric-value-line').element.firstElementChild
      ?.querySelector('.metric-delta')).not.toBeNull()
    expect(wrapper.findAll('.block-values .metric-delta')).toHaveLength(1)
    expect(wrapper.get('.block-values .metric-value-line').element.firstElementChild
      ?.querySelector('.metric-delta')).not.toBeNull()
    expect(wrapper.findAll('.sub-cell .metric-delta').map((node) => node.attributes('aria-label'))).toEqual([
      '100.0% ↑', '100.0% ↑',
    ])
    expect(wrapper.findAll('.detail-summary .metric-delta')).toHaveLength(3)
    expect(wrapper.findAll('.detail-row .metric-delta')).toHaveLength(12)
    expect(wrapper.get('.detail-row-value').element.firstElementChild
      ?.querySelector('.metric-delta')).not.toBeNull()
  })

  it('分块总 Mip 与当前选中分块指标分别计算动态色阶', async () => {
    const comparisonOverview = overviewWithComparison()
    const currentMetrics = {
      ...metrics(100),
      all_mips_bytes: 110,
      cook_estimate_bytes: 400,
      texture_count: 4,
    }
    const previousMetrics = {
      ...metrics(100),
      all_mips_bytes: 100,
      cook_estimate_bytes: 100,
      texture_count: 1,
    }
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithoutBlocks,
      available_batches: comparisonOverview.available_batches,
      comparison: comparisonOverview.comparison,
      world: {
        ...overviewWithoutBlocks.world,
        metrics: currentMetrics,
        self_metrics: currentMetrics,
        subtree_metrics: currentMetrics,
        comparison_metrics: { self: previousMetrics, subtree: previousMetrics },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.getComponent(MapBuildAtlas).props('comparisonProps').percentRange).toEqual([0, 10])
    expect(wrapper.getComponent(MapBuildDetailPanel).props('comparisonProps').percentRange).toEqual([0, 300])
  })

  it('可以选择一个明确的历史批次作为对比基准', async () => {
    apiMock.mapBuildOverview.mockResolvedValueOnce(overviewWithComparison())
    const wrapper = mountView()
    await flushPromises()
    vi.clearAllMocks()
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithComparison(),
      comparison: {
        selection: '0',
        batch: batch('0', '2026-07-20T09:30'),
        default_batch: batch('1', '2026-07-29T09:30'),
        available_batches: [
          batch('2', '2026-08-05T10:00'),
          batch('1', '2026-07-29T09:30'),
          batch('0', '2026-07-20T09:30'),
        ],
      },
    })

    const compareSelect = wrapper.findComponent('.compare-select')
    await compareSelect.vm.$emit('update:modelValue', 'batch:0')
    await compareSelect.vm.$emit('change', 'batch:0')
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '2',
      comparison_mode: 'batch',
      comparison_batch_id: '0',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).not.toHaveBeenCalled()
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('batch:0')
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      query: expect.objectContaining({ compare: 'batch', compare_batch: '0' }),
    }))
  })

  it('清除对比批次后停止对比并把状态写入 URL', async () => {
    apiMock.mapBuildOverview.mockResolvedValueOnce(overviewWithComparison())
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.get('.compare-select').attributes('allow-clear')).toBeDefined()
    vi.clearAllMocks()
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithComparison(),
      comparison: {
        selection: 'off',
        batch: null,
        default_batch: batch('1', '2026-07-29T09:30'),
        available_batches: overviewWithComparison().available_batches,
      },
    })

    const compareSelect = wrapper.findComponent('.compare-select')
    await compareSelect.vm.$emit('update:modelValue', undefined)
    await compareSelect.vm.$emit('change', undefined)
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '2',
      comparison_mode: 'off',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('')
    expect(wrapper.findAll('.metric-delta')).toHaveLength(0)
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      query: expect.objectContaining({ compare: 'off' }),
    }))
  })

  it('当前场景关闭对比后切换场景仍默认使用上一批次', async () => {
    apiMock.mapBuildMeta.mockResolvedValueOnce({
      ...meta,
      scene_ids: [
        ...meta.scene_ids,
        {
          value: 'Forest_WP', batch_count: 2, latest_at: '2026-08-06T10:00',
          platforms: ['Windows'], shading_qualities: [{ value: 5, label: '电影' }],
        },
      ],
    })
    apiMock.mapBuildOverview.mockResolvedValueOnce(overviewWithComparison())
    const wrapper = mountView()
    await flushPromises()

    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithComparison(),
      comparison: {
        selection: 'off',
        batch: null,
        default_batch: batch('1', '2026-07-29T09:30'),
        available_batches: overviewWithComparison().available_batches,
      },
    })
    const compareSelect = wrapper.findComponent('.compare-select')
    await compareSelect.vm.$emit('update:modelValue', undefined)
    await compareSelect.vm.$emit('change', undefined)
    await flushPromises()
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('')

    const forestOverview = {
      ...overviewWithComparison(),
      batch: { ...batch('9', '2026-08-06T10:00'), scene_id: 'Forest_WP' },
    }
    apiMock.mapBuildOverview.mockResolvedValueOnce(forestOverview)
    apiMock.mapBuildTrend.mockResolvedValueOnce(worldTrend)
    vi.clearAllMocks()

    const sceneSelect = wrapper.findComponent('.scene-select')
    await sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    await sceneSelect.vm.$emit('change', 'Forest_WP')
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Forest_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('previous')
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      path: '/map-build/Forest_WP',
      query: expect.objectContaining({ compare: 'previous' }),
    }))
  })

  it('重复点击当前分块不重复请求趋势，失败后仍可点击重试', async () => {
    const wrapper = mountView()
    await flushPromises()
    vi.clearAllMocks()

    await wrapper.get('.world-head').trigger('click')
    await flushPromises()
    expect(apiMock.mapBuildTrend).not.toHaveBeenCalled()
    expect(routerMock.replace).not.toHaveBeenCalled()

    apiMock.mapBuildTrend.mockRejectedValueOnce(new Error('trend failed'))
    await wrapper.get('.block-head').trigger('click')
    await flushPromises()
    expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('trend failed')

    apiMock.mapBuildTrend.mockResolvedValueOnce(worldTrend)
    await wrapper.get('.block-head').trigger('click')
    await flushPromises()
    expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(2)
  })

  it('元数据响应结构异常时显示错误而不是让页面崩溃', async () => {
    apiMock.mapBuildMeta.mockResolvedValueOnce({ scene_ids: null })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('烘培数据筛选项格式无效')
    expect(wrapper.text()).toContain('请选择场景')
    expect(wrapper.findAll('.scene-option').map((option) => option.text())).toEqual([
      'Forest_WP', 'Coral_WP', 'Unlisted_WP未配置',
    ])
    expect(apiMock.mapBuildOverview).not.toHaveBeenCalled()
    expect(apiMock.mapBuildTrend).not.toHaveBeenCalled()
  })

  it('普通场景没有分块树时展示提示并隐藏统计口径切换', async () => {
    apiMock.mapBuildOverview.mockResolvedValueOnce(overviewWithoutBlocks)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('.no-block-tree').text()).toBe('该场景没有分块数据，仅展示主分块数据')
    expect(wrapper.find('.block-layout').exists()).toBe(false)
    expect(wrapper.find('.atlas-card-footer').exists()).toBe(false)
    expect(wrapper.find('.metric-scope-switch').exists()).toBe(false)
    expect(wrapper.get('.world-total small').text()).toBe('仅自身')
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.find('.detail-eyebrow').exists()).toBe(false)
    expect(wrapper.get('.atlas-card').classes()).toContain('world-selected')
    expect(wrapper.get('.atlas-card').classes()).not.toContain('self-head-selected')
  })

  it('仅自身只高亮父节点头部，含子级时高亮整个父节点卡片', async () => {
    const wrapper = mountView()
    await flushPromises()

    const atlas = wrapper.get('.atlas-card')
    expect(atlas.classes()).toContain('self-head-selected')
    expect(atlas.classes()).not.toContain('world-selected')

    await wrapper.get('.block-head').trigger('click')
    await flushPromises()
    const block = wrapper.get('.block-panel')
    expect(block.classes()).toContain('self-head-selected')
    expect(block.classes()).not.toContain('selected')
    expect(mapBuildAtlasSource).toMatch(
      /\.atlas-card\.self-head-selected > \.world-head \{[^}]*border-top-left-radius: inherit; border-top-right-radius: inherit;/s,
    )
    expect(mapBuildAtlasSource).toMatch(
      /\.block-panel\.self-head-selected > \.block-head \{[^}]*border-top-left-radius: inherit; border-top-right-radius: inherit;/s,
    )
    expect(mapBuildAtlasSource).toMatch(
      /\.block-panel\.self-head-selected > \.block-head \{[^}]*box-shadow: inset 0 0 0 1px/s,
    )
    expect(mapBuildAtlasSource).toMatch(
      /\.block-panel\.self-head-selected > \.block-head \{[^}]*background: color-mix\(in srgb, rgb\(var\(--arcoblue-6\)\) 7%, transparent\)/s,
    )
    expect(mapBuildAtlasSource).toMatch(/\.block-panel \{[^}]*border-radius: 0;/s)
    expect(mapBuildAtlasSource).toMatch(/\.auxiliary-block \{[^}]*border-radius: 0;/s)
    expect(mapBuildAtlasSource).not.toContain('.block-panel.self-head-selected::after')

    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(block.classes()).not.toContain('self-head-selected')
    expect(block.classes()).toContain('selected')

    await wrapper.get('.world-head').trigger('click')
    await flushPromises()
    expect(atlas.classes()).not.toContain('self-head-selected')
    expect(atlas.classes()).toContain('world-selected')
  })

  it('子分块网格使用平面样式且保留克制的交互反馈', () => {
    const selectedRule = mapBuildAtlasSource.match(/\.sub-cell\.selected \{[^}]+\}/)?.[0]

    expect(mapBuildAtlasSource).not.toContain('.sub-cell::before')
    expect(mapBuildAtlasSource).not.toContain('.sub-cell::after')
    expect(mapBuildAtlasSource).toMatch(
      /\.sub-grid \{[^}]*gap: 0; background: transparent;/s,
    )
    expect(mapBuildAtlasSource).toMatch(
      /\.sub-cell:not\(:nth-child\(4n\)\) \{ border-right: 1px solid rgba\(0,0,0,\.26\); \}/,
    )
    expect(mapBuildAtlasSource).toMatch(
      /\.sub-cell:nth-child\(-n\+12\) \{ border-bottom: 1px solid rgba\(0,0,0,\.26\); \}/,
    )
    expect(mapBuildAtlasSource).toMatch(
      /\.sub-cell:hover \{ background-image: linear-gradient\(rgba\(255,255,255,\.055\), rgba\(255,255,255,\.055\)\); \}/,
    )
    expect(mapBuildAtlasSource).toMatch(/\.sub-cell \{[^}]*contain: paint;/s)
    expect(mapBuildAtlasSource).not.toMatch(/\.sub-cell:hover \{[^}]*filter:/s)
    expect(selectedRule).toContain('box-shadow: inset 0 0 0 2px #91bdff;')
    expect(selectedRule?.match(/#91bdff/g)).toHaveLength(1)
    expect(mapBuildAtlasSource).not.toMatch(/\.sub-cell b \{[^}]*text-shadow:/s)
  })

  it('分块面板不再显示重复的原生 Hover 提示', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('.atlas-card').findAll('[title]')).toHaveLength(0)
  })

  it('异常网格值不会污染正常格子的全局热力色阶', async () => {
    const [firstCell, secondCell] = overview.blocks[0].sub_blocks
    const invalidMetrics = { ...firstCell.metrics, all_mips_bytes: Number.NaN }
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      blocks: [{
        ...overview.blocks[0],
        sub_blocks: [
          { ...firstCell, metrics: invalidMetrics, self_metrics: invalidMetrics },
          secondCell,
        ],
      }],
    })

    const wrapper = mountView()
    await flushPromises()

    const cells = wrapper.findAll('.sub-cell')
    expect(cells[0].attributes('style')).toContain('rgb(33, 72, 118)')
    expect(cells[1].attributes('style')).toContain('rgb(222, 132, 35)')
  })

  it('只有反射分块时不误判为空场景', async () => {
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      blocks: [],
      world: { ...overview.world, has_children: true },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.no-block-tree').exists()).toBe(false)
    expect(wrapper.find('.block-layout').exists()).toBe(false)
    expect(wrapper.get('.atlas-card-footer').classes()).toContain('auxiliary-only')
    expect(wrapper.get('.auxiliary-block').text()).toBe('反射分块12.00 MiB')
    expect(wrapper.find('.metric-scope-switch').exists()).toBe(true)
  })

  it('场景深链直接加载该场景最新烘培批次', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent('.scene-select').props('modelValue')).toBe('Coral_WP')
    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Coral_WP',
      query: {
        branch_tag: 'main', range_mode: 'rolling', batch: '2', compare: 'previous', scope: 'self',
      },
    })
  })

  it('分支深链只加载该分支的烘培元数据、网格和趋势', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = { branch_tag: 'engine-ue5' }

    mountView()
    await flushPromises()

    expect(apiMock.mapBuildMeta).toHaveBeenCalledWith(
      { branch_tag: 'engine-ue5' },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith(
      'Coral_WP',
      expect.objectContaining({ branch_tag: 'engine-ue5' }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith(
      'Coral_WP',
      expect.objectContaining({ branch_tag: 'engine-ue5' }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('首屏等待全局元数据后再校验分支深链，避免有效分支闪回 main', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = { branch_tag: 'engine-ue5' }
    storeMock.initialized = false
    storeMock.meta.branch_tags = ['main']
    storeMock.init.mockImplementation(async (_sceneId, branchTag) => {
      storeMock.meta.branch_tags = ['main', 'engine-ue5']
      storeMock.filters.branch_tag = branchTag
      storeMock.initialized = true
    })

    mountView()
    await flushPromises()

    expect(storeMock.init).toHaveBeenCalledWith()
    expect(apiMock.mapBuildMeta).toHaveBeenCalledWith(
      { branch_tag: 'engine-ue5' },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('未知分支深链回退 main 并修正地址栏', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = { branch_tag: 'missing-branch' }

    mountView()
    await flushPromises()

    expect(storeMock.filters.branch_tag).toBe('main')
    expect(apiMock.mapBuildMeta).toHaveBeenCalledWith(
      { branch_tag: 'main' },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      query: expect.objectContaining({ branch_tag: 'main' }),
    }))
  })

  it('重新进入页面时选择最新批次并恢复日期范围、分块和统计口径', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = {
      batch: '1', compare: 'batch', compare_batch: '0',
      range_mode: 'fixed', from: '2026-07-01', to: '2026-08-05',
      scope: 'subtree', block: '3', sub: '1',
    }
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: batch('1', '2026-08-04T10:00'),
      batch_window: { start_date: '2026-07-01', end_date: '2026-08-05' },
      comparison: {
        selection: '0',
        batch: batch('0', '2026-08-03T10:00'),
        available_batches: [batch('0', '2026-08-03T10:00')],
      },
    })
    apiMock.mapBuildTrend.mockResolvedValueOnce({
      ...worldTrend,
      selection: { label: '分块 3 / 子分块 0x01' },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      batch_start: '2026-07-01',
      batch_end: '2026-08-05',
      comparison_mode: 'batch',
      comparison_batch_id: '0',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      start_date: '2026-07-01',
      end_date: '2026-08-05',
      metric_scope: 'subtree',
      block_index: 3,
      sub_block_index: 1,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('1')
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3 / 0x01（含子级汇总）')
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('batch:0')
    expect(wrapper.findComponent('.batch-date-picker').props('modelValue')).toEqual([
      '2026-07-01', '2026-08-05',
    ])
  })

  it('旧的 compare=1 参数会回退到上一批次', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = { compare: '1' }
    apiMock.mapBuildOverview.mockResolvedValueOnce(overviewWithComparison())

    const wrapper = mountView()
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('previous')
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      query: expect.objectContaining({ compare: 'previous' }),
    }))
  })

  it('重新进入带 compare=off 的旧页面时恢复默认上一批次', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = {
      range_mode: 'fixed', from: '2026-07-01', to: '2026-08-05',
      batch: '2', compare: 'off', scope: 'self',
    }
    apiMock.mapBuildOverview.mockImplementationOnce((_sceneId, params) => {
      if (params.comparison_mode === 'previous') return Promise.resolve(overviewWithComparison())
      return Promise.resolve({
        ...overviewWithComparison(),
        comparison: {
          selection: 'off',
          batch: null,
          default_batch: batch('1', '2026-07-29T09:30'),
          available_batches: overviewWithComparison().available_batches,
        },
      })
    })

    const wrapper = mountView()
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      batch_start: '2026-07-01',
      batch_end: '2026-08-05',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.compare-select').props('modelValue')).toBe('previous')
    expect(routerMock.replace).toHaveBeenLastCalledWith(expect.objectContaining({
      query: expect.objectContaining({ compare: 'previous' }),
    }))
  })

  it('选择分块后把可分享的完整分析状态写入 URL', async () => {
    const wrapper = mountView()
    await flushPromises()
    vi.clearAllMocks()

    await wrapper.findAll('.sub-cell')[1].trigger('click')
    await flushPromises()

    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Coral_WP',
      query: {
        branch_tag: 'main', range_mode: 'rolling', batch: '2', compare: 'previous',
        scope: 'self', block: '3', sub: '1',
      },
    })
  })

  it('批次切换加载时保留旧网格，失败后回滚到上一个成功批次', async () => {
    const wrapper = mountView()
    await flushPromises()
    const pendingOverview = deferred()
    apiMock.mapBuildOverview.mockReturnValueOnce(pendingOverview.promise)

    const batchSelect = wrapper.findComponent('.batch-select')
    await batchSelect.vm.$emit('update:modelValue', '1')
    batchSelect.vm.$emit('change', '1')
    await Promise.resolve()

    expect(wrapper.get('.overview-loading-veil').text()).toContain('正在切换批次')
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')

    pendingOverview.reject(new Error('temporary failure'))
    await flushPromises()

    expect(wrapper.find('.overview-loading-veil').exists()).toBe(false)
    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('2')
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.text()).toContain('temporary failure')
  })


  it('首屏概览返回前不误用整卡高亮，数据就绪后直接进入正确选中态', async () => {
    const pendingOverview = deferred()
    apiMock.mapBuildOverview.mockReturnValueOnce(pendingOverview.promise)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.atlas-card').exists()).toBe(true)
    expect(wrapper.get('.atlas-card').classes()).not.toContain('world-selected')
    expect(wrapper.get('.atlas-card').classes()).not.toContain('self-head-selected')

    pendingOverview.resolve(overview)
    await flushPromises()

    expect(wrapper.get('.atlas-card').classes()).not.toContain('world-selected')
    expect(wrapper.get('.atlas-card').classes()).toContain('self-head-selected')
  })

  it('向顶栏注册刷新动作并移除筛选卡内的重复按钮', async () => {
    const wrapper = mountView()
    await flushPromises()
    vi.clearAllMocks()
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: batch('3', '2026-08-06T10:00'),
      available_batches: [
        batch('3', '2026-08-06T10:00'),
        ...overview.available_batches,
      ],
    })

    expect(wrapper.find('.refresh-button').exists()).toBe(false)
    expect(await runPageRefresh()).toBe(true)
    await flushPromises()
    expect(apiMock.mapBuildMeta).toHaveBeenCalledTimes(1)
    expect(apiMock.mapBuildOverview).toHaveBeenCalledTimes(1)
    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(1)
    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('3')

    wrapper.unmount()
    expect(await runPageRefresh()).toBe(false)
  })

  it('连续刷新乱序完成时过期刷新不能清空最新页面', async () => {
    const wrapper = mountView()
    await flushPromises()

    const staleMeta = deferred()
    const latestMeta = deferred()
    apiMock.mapBuildMeta
      .mockImplementationOnce(() => staleMeta.promise)
      .mockImplementationOnce(() => latestMeta.promise)

    const staleRefresh = runPageRefresh()
    const latestRefresh = runPageRefresh()
    latestMeta.resolve(meta)
    await latestRefresh
    await flushPromises()
    expect(wrapper.find('.atlas-card').exists()).toBe(true)

    staleMeta.resolve(meta)
    await staleRefresh
    await flushPromises()

    expect(wrapper.find('.atlas-card').exists()).toBe(true)
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.findComponent('.scene-select').props('modelValue')).toBe('Coral_WP')
  })

  it('刷新临时失败时保留上一次成功数据并允许再次刷新恢复', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.get('.trend-stub').text()).toBe('1 points')

    apiMock.mapBuildOverview.mockRejectedValueOnce(new Error('overview temporarily unavailable'))
    await runPageRefresh()
    await flushPromises()

    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.get('.trend-stub').text()).toBe('1 points')
    expect(wrapper.text()).toContain('temporarily unavailable')

    await runPageRefresh()
    await flushPromises()
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.get('.trend-stub').text()).toBe('1 points')
    expect(wrapper.text()).not.toContain('temporarily unavailable')
  })

  it('离开页面时取消正在进行的概览和趋势刷新', async () => {
    const wrapper = mountView()
    await flushPromises()

    const pendingUntilAbort = (...args) => new Promise((_resolve, reject) => {
      const signal = args.at(-1).signal
      signal.addEventListener('abort', () => reject({ code: 'ABORTED' }), { once: true })
    })
    apiMock.mapBuildOverview.mockResolvedValueOnce(overview)
    apiMock.mapBuildTrend.mockImplementationOnce(pendingUntilAbort)
    const overviewCalls = apiMock.mapBuildOverview.mock.calls.length
    const trendCalls = apiMock.mapBuildTrend.mock.calls.length

    const refreshing = runPageRefresh()
    await vi.waitFor(() => {
      expect(apiMock.mapBuildOverview).toHaveBeenCalledTimes(overviewCalls + 1)
      expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(trendCalls + 1)
    })
    const overviewSignal = apiMock.mapBuildOverview.mock.calls.at(-1)[2].signal
    const trendSignal = apiMock.mapBuildTrend.mock.calls.at(-1)[2].signal

    wrapper.unmount()

    expect(overviewSignal.aborted).toBe(true)
    expect(trendSignal.aborted).toBe(true)
    await expect(refreshing).resolves.toBe(true)
    expect(await runPageRefresh()).toBe(false)
  })

  it('场景筛选复用批次管理目录，并为没有烘培数据的场景展示空状态', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('.scene-field .label').text()).toBe('场景ID')
    expect(wrapper.get('.scene-select').attributes('size')).toBe('small')
    expect(wrapper.findAll('.scene-option').map((option) => option.text())).toEqual([
      'Forest_WP', 'Coral_WP', 'Unlisted_WP未配置',
    ])
    const sceneNames = wrapper.findAll('.scene-option-name')
    expect(sceneNames.map((name) => name.classes('is-data-empty'))).toEqual([
      true, false, true,
    ])
    expect(sceneNames[0].attributes('title')).toBe('当前分支没有烘培数据')
    expect(sceneNames[1].attributes('title')).toBeUndefined()
    const sceneSelect = wrapper.findComponent('.scene-select')
    expect(sceneSelect.props('modelValue')).toBe('Coral_WP')

    await sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    await sceneSelect.vm.$emit('change', 'Forest_WP')
    await flushPromises()

    expect(wrapper.text()).toContain('该场景还没有烘培数据')
    expect(wrapper.find('.atlas-card').exists()).toBe(false)
    expect(apiMock.mapBuildOverview).toHaveBeenCalledTimes(1)
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Forest_WP', query: { branch_tag: 'main', range_mode: 'rolling' },
    })
  })

  it('卡片右下统计口径统一控制网格并在切换节点后保持不变', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.atlas-scope-bar').exists()).toBe(false)
    expect(wrapper.get('.world-head').text()).not.toContain('统计口径')
    expect(wrapper.get('.metric-scope-switch').element.closest('.atlas-card-footer')).not.toBeNull()
    expect(wrapper.get('.atlas-card-footer .metric-scope-switch button[aria-pressed="true"]').text()).toBe('仅自身')
    expect(wrapper.find('.world-head .metric-scope-switch').exists()).toBe(false)
    expect(wrapper.find('.detail-head .metric-scope-switch').exists()).toBe(false)
    expect(wrapper.get('.world-total small').text()).toBe('仅自身')
    expect(wrapper.get('.block-values small').text()).toBe('仅自身')

    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.get('.world-total small').text()).toBe('含子级汇总')
    expect(wrapper.get('.block-values small').text()).toBe('含子级汇总')

    await wrapper.get('.block-head').trigger('click')
    await flushPromises()
    expect(wrapper.get('.world-total small').text()).toBe('含子级汇总')
    expect(wrapper.get('.block-values small').text()).toBe('含子级汇总')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'subtree', block_index: 3,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))

    await wrapper.findAll('.sub-cell')[0].trigger('click')
    await flushPromises()
    expect(wrapper.get('.world-total small').text()).toBe('含子级汇总')
    expect(wrapper.get('.block-values small').text()).toBe('含子级汇总')
    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('含子级')
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3 / 0x00（含子级汇总）')
    expect(wrapper.find('.detail-eyebrow').exists()).toBe(false)
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'subtree', block_index: 3, sub_block_index: 0,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('反射分块在网格左下紧凑展示并可查询独立详情与趋势', async () => {
    const wrapper = mountView()
    await flushPromises()

    const footer = wrapper.get('.atlas-card-footer')
    const reflection = footer.get('.auxiliary-block')
    expect(reflection.text()).toBe('反射分块12.00 MiB')
    expect(reflection.text()).not.toContain('仅自身')
    expect(reflection.text()).not.toContain('含子级')
    expect(footer.get('.atlas-scope-control').exists()).toBe(true)

    await reflection.trigger('click')
    await flushPromises()

    expect(reflection.attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('.detail-head h3').text()).toBe('反射分块')
    expect(wrapper.get('.detail-head p').text()).toBe('/reflection')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main',
      ...defaultTrendRange,
      metric_scope: 'self',
      registry_path: '/reflection',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))

    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.get('.auxiliary-block').text()).toBe('反射分块12.00 MiB')
    expect(wrapper.get('.detail-head h3').text()).toBe('反射分块')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main',
      ...defaultTrendRange,
      metric_scope: 'self',
      registry_path: '/reflection',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('只按场景加载概览，先展示网格并在点击子分块后请求对应趋势', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.text()).not.toContain('平台')
    expect(wrapper.text()).not.toContain('画质')
    expect(wrapper.get('.atlas-card').element.compareDocumentPosition(
      wrapper.get('.trend-card').element,
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(wrapper.text()).toContain('分块 3')
    expect(wrapper.findAll('.sub-cell')).toHaveLength(2)
    expect(wrapper.get('.atlas-card').find('.detail-panel').exists()).toBe(false)
    expect(wrapper.get('.detail-panel').element.parentElement).toBe(wrapper.get('.atlas-row').element)
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.get('.detail-head p').text()).toBe('/root')
    expect(wrapper.find('.world-select small').exists()).toBe(false)
    expect(wrapper.find('.detail-eyebrow').exists()).toBe(false)
    expect(wrapper.findAll('.metric-scope-switch button')).toHaveLength(2)
    expect(wrapper.get('.metric-scope-switch').element.closest('.atlas-card-footer')).not.toBeNull()
    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('仅自身')
    expect(wrapper.get('.atlas-card').classes()).toContain('self-head-selected')
    expect(wrapper.get('.atlas-card').classes()).not.toContain('world-selected')
    expect(wrapper.get('.world-head').attributes('aria-pressed')).toBe('true')
    expect(wrapper.findAll('.detail-row')).toHaveLength(12)
    expect(wrapper.text()).toContain('总 Mip')
    expect(wrapper.text()).toContain('Cook 估算')
    expect(wrapper.findAll('.detail-summary > div > span:first-child').map((node) => node.text())).toEqual([
      '总 Mip', 'Cook 估算', '纹理数',
    ])
    expect(wrapper.get('.world-total small').text()).toBe('仅自身')
    expect(wrapper.get('.world-total b').attributes('title')).toBeUndefined()
    expect(wrapper.get('.world-total').text()).not.toContain('Cook 估算')
    expect(wrapper.find('.atlas-foot').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('驻留总大小')
    expect(wrapper.text()).not.toContain('纹理数量')
    expect(wrapper.text()).not.toContain('采集时占用')
    expect(wrapper.text()).not.toContain('驻留总量')
    expect(wrapper.text()).toContain('主分块')
    expect(wrapper.findAll('.sub-cell b').every((node) => node.text().endsWith('MiB'))).toBe(true)
    expect(wrapper.findAll('.detail-row-head b').every((node) => node.text().endsWith('MiB'))).toBe(true)
    expect(wrapper.text()).not.toContain('相对前批')

    await wrapper.get('.block-head').trigger('click')
    await flushPromises()
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3')
    expect(wrapper.get('.detail-head p').text()).toBe('/block3')
    expect(wrapper.get('.atlas-card').classes()).not.toContain('world-selected')
    expect(wrapper.get('.block-panel').classes()).toContain('self-head-selected')
    expect(wrapper.get('.block-panel').classes()).not.toContain('selected')
    expect(wrapper.get('.block-head').attributes('aria-pressed')).toBe('true')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'self', block_index: 3,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('仅自身')

    apiMock.mapBuildTrend.mockResolvedValueOnce({
      selection: { label: '分块 3 · 含子级汇总' }, points: [],
    })
    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'subtree', block_index: 3,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3（含子级汇总）')
    expect(wrapper.get('.block-panel').classes()).toContain('selected')
    expect(wrapper.get('.block-panel').classes()).not.toContain('self-head-selected')
    expect(wrapper.find('.detail-note').exists()).toBe(false)

    apiMock.mapBuildTrend.mockResolvedValueOnce({
      selection: { label: '分块 3 / 子分块 0x01' }, points: [],
    })
    await wrapper.findAll('.sub-cell')[1].trigger('click')
    await flushPromises()

    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'subtree', block_index: 3, sub_block_index: 1,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.get('.selection-pill').text()).toBe('分块 3 / 子分块 0x01')
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3 / 0x01（含子级汇总）')
    expect(wrapper.get('.detail-head p').text()).toBe('/1')
    expect(wrapper.find('.metric-scope-switch').exists()).toBe(true)
    expect(wrapper.get('.block-panel').classes()).not.toContain('selected')

    apiMock.mapBuildTrend.mockResolvedValueOnce(worldTrend)
    await wrapper.get('.world-head').trigger('click')
    await flushPromises()
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块（含子级汇总）')
    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('含子级')
    expect(wrapper.get('.atlas-card').classes()).toContain('world-selected')
    expect(wrapper.get('.world-head').attributes('aria-pressed')).toBe('true')
  })

  it('快速切换子分块会取消旧趋势请求，晚到结果不能覆盖最新选择', async () => {
    const wrapper = mountView()
    await flushPromises()

    const oldRequest = deferred()
    const latestRequest = deferred()
    apiMock.mapBuildTrend
      .mockImplementationOnce(() => oldRequest.promise)
      .mockImplementationOnce(() => latestRequest.promise)

    await wrapper.findAll('.sub-cell')[0].trigger('click')
    const oldSignal = apiMock.mapBuildTrend.mock.calls.at(-1)[2].signal
    await wrapper.findAll('.sub-cell')[1].trigger('click')
    expect(oldSignal.aborted).toBe(true)

    latestRequest.resolve({ selection: { label: '最新 0x01' }, points: [] })
    await flushPromises()
    expect(wrapper.get('.selection-pill').text()).toBe('最新 0x01')

    oldRequest.resolve({ selection: { label: '过期 0x00' }, points: [] })
    await flushPromises()
    expect(wrapper.get('.selection-pill').text()).toBe('最新 0x01')
  })

  it('切换场景时立即取消旧场景仍在进行的趋势请求', async () => {
    apiMock.mapBuildMeta.mockResolvedValueOnce({
      ...meta,
      scene_ids: [
        ...meta.scene_ids,
        {
          value: 'Forest_WP', batch_count: 1, latest_at: '2026-08-06T10:00',
          platforms: ['Windows'], shading_qualities: [{ value: 5, label: '电影' }],
        },
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    const staleTrend = deferred()
    apiMock.mapBuildTrend.mockImplementationOnce(() => staleTrend.promise)
    await wrapper.findAll('.sub-cell')[0].trigger('click')
    await Promise.resolve()
    const staleTrendSignal = apiMock.mapBuildTrend.mock.calls.at(-1)[2].signal

    const nextOverview = deferred()
    apiMock.mapBuildOverview.mockImplementationOnce(() => nextOverview.promise)
    const sceneSelect = wrapper.findComponent('.scene-select')
    sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    sceneSelect.vm.$emit('change', 'Forest_WP')
    await Promise.resolve()

    expect(staleTrendSignal.aborted).toBe(true)

    nextOverview.resolve({
      ...overview,
      batch: { ...batch('9', '2026-08-06T10:00'), scene_id: 'Forest_WP' },
    })
    staleTrend.resolve({ selection: { label: '过期场景趋势' }, points: [] })
    await flushPromises()
  })

  it('快速切换场景时概览和趋势都以最后一次选择为准', async () => {
    apiMock.mapBuildMeta.mockResolvedValueOnce({
      ...meta,
      scene_ids: [
        ...meta.scene_ids,
        {
          value: 'Forest_WP', batch_count: 1, latest_at: '2026-08-06T10:00',
          platforms: ['Windows'], shading_qualities: [{ value: 5, label: '电影' }],
        },
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    const staleOverview = deferred()
    const latestOverview = deferred()
    const latestTrend = deferred()
    apiMock.mapBuildOverview
      .mockImplementationOnce(() => staleOverview.promise)
      .mockImplementationOnce(() => latestOverview.promise)
    apiMock.mapBuildTrend
      .mockImplementationOnce(() => latestTrend.promise)
    const trendCalls = apiMock.mapBuildTrend.mock.calls.length

    const sceneSelect = wrapper.findComponent('.scene-select')
    sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    sceneSelect.vm.$emit('change', 'Forest_WP')
    await Promise.resolve()
    const staleOverviewSignal = apiMock.mapBuildOverview.mock.calls.at(-1)[2].signal
    expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(trendCalls)

    sceneSelect.vm.$emit('update:modelValue', 'Coral_WP')
    sceneSelect.vm.$emit('change', 'Coral_WP')
    await Promise.resolve()
    expect(staleOverviewSignal.aborted).toBe(true)

    latestOverview.resolve(overview)
    await vi.waitFor(() => {
      expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(trendCalls + 1)
    })
    latestTrend.resolve(worldTrend)
    await flushPromises()
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.get('.selection-pill').text()).toBe('主分块 · 仅自身')

    staleOverview.resolve({
      ...overviewWithoutBlocks,
      batch: { ...batch('9', '2026-08-06T10:00'), scene_id: 'Forest_WP' },
    })
    await flushPromises()

    expect(wrapper.findComponent('.scene-select').props('modelValue')).toBe('Coral_WP')
    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('2')
    expect(wrapper.get('.selection-pill').text()).toBe('主分块 · 仅自身')
  })

  it('切换场景时保留含子级统计口径', async () => {
    apiMock.mapBuildMeta.mockResolvedValueOnce({
      ...meta,
      scene_ids: [
        ...meta.scene_ids,
        {
          value: 'Forest_WP', batch_count: 1, latest_at: '2026-08-06T10:00',
          platforms: ['Windows'], shading_qualities: [{ value: 5, label: '电影' }],
        },
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    vi.clearAllMocks()

    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: { ...batch('9', '2026-08-06T10:00'), scene_id: 'Forest_WP' },
    })
    apiMock.mapBuildTrend.mockResolvedValueOnce({
      ...worldTrend,
      selection: { ...worldTrend.selection, metric_scope: 'subtree', label: '主分块 · 含子级汇总' },
    })
    const sceneSelect = wrapper.findComponent('.scene-select')
    sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    sceneSelect.vm.$emit('change', 'Forest_WP')
    await flushPromises()

    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('含子级')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Forest_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'subtree',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Forest_WP',
      query: expect.objectContaining({ scope: 'subtree' }),
    })
  })

  it('目标场景没有子级时自动改用仅自身趋势', async () => {
    apiMock.mapBuildMeta.mockResolvedValueOnce({
      ...meta,
      scene_ids: [
        ...meta.scene_ids,
        {
          value: 'Forest_WP', batch_count: 1, latest_at: '2026-08-06T10:00',
          platforms: ['Windows'], shading_qualities: [{ value: 5, label: '电影' }],
        },
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    vi.clearAllMocks()

    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithoutBlocks,
      batch: { ...batch('9', '2026-08-06T10:00'), scene_id: 'Forest_WP' },
    })
    apiMock.mapBuildTrend.mockResolvedValueOnce(worldTrend)
    const sceneSelect = wrapper.findComponent('.scene-select')
    sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    sceneSelect.vm.$emit('change', 'Forest_WP')
    await flushPromises()

    expect(wrapper.find('.metric-scope-switch').exists()).toBe(false)
    expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(1)
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Forest_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Forest_WP',
      query: expect.objectContaining({ scope: 'self' }),
    })
  })

  it('切换到缺少当前分块的批次时同步回到主分块趋势', async () => {
    const wrapper = mountView()
    await flushPromises()

    apiMock.mapBuildTrend.mockResolvedValueOnce({
      selection: { label: '分块 3 · 自身数据' }, points: [],
    })
    await wrapper.get('.block-head').trigger('click')
    await flushPromises()
    expect(wrapper.get('.selection-pill').text()).toBe('分块 3 · 仅自身')

    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithoutBlocks,
      batch: batch('1', '2026-08-04T10:00'),
    })
    apiMock.mapBuildTrend.mockResolvedValueOnce(worldTrend)
    const batchSelect = wrapper.findComponent('.batch-select')
    await batchSelect.vm.$emit('update:modelValue', '1')
    await batchSelect.vm.$emit('change', '1')
    await flushPromises()

    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.get('.selection-pill').text()).toBe('主分块 · 仅自身')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('点击趋势点会复用基线批次切换流程并更新当前批次', async () => {
    const wrapper = mountView()
    await flushPromises()

    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: batch('1', '2026-08-04T10:00'),
    })
    const chart = wrapper.findComponent('.trend-stub')
    await chart.vm.$emit('selectBatch', batch('1', '2026-08-04T10:00'))
    await flushPromises()

    expect(apiMock.mapBuildOverview).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main',
      batch_id: '1',
      comparison_mode: 'previous',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('1')
    expect(chart.props('currentBatchId')).toBe('1')
  })

  it('切换批次导致统计口径自动降级时同步刷新趋势口径', async () => {
    const wrapper = mountView()
    await flushPromises()

    apiMock.mapBuildTrend.mockResolvedValueOnce({
      ...worldTrend,
      selection: {
        scope: 'main_block', metric_scope: 'subtree', label: '主分块 · 含子级汇总',
      },
    })
    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.get('.selection-pill').text()).toBe('主分块 · 含子级汇总')

    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overviewWithoutBlocks,
      batch: batch('1', '2026-08-04T10:00'),
    })
    apiMock.mapBuildTrend.mockResolvedValueOnce(worldTrend)
    const batchSelect = wrapper.findComponent('.batch-select')
    await batchSelect.vm.$emit('update:modelValue', '1')
    await batchSelect.vm.$emit('change', '1')
    await flushPromises()

    expect(wrapper.find('.metric-scope-switch').exists()).toBe(false)
    expect(wrapper.get('.world-total small').text()).toBe('仅自身')
    expect(wrapper.get('.selection-pill').text()).toBe('主分块 · 仅自身')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', ...defaultTrendRange, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })
})
