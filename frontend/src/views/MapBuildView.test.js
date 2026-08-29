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
import mapBuildViewSource from './MapBuildView.vue?raw'
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
const worldTrend = {
  selection: { scope: 'main_block', metric_scope: 'self', label: '主分块 · 自身数据' },
  points: [{ batch: batch('1', '2026-08-04T10:00'), metrics: metrics(100) }],
  window: { days: 30, start_date: '2026-07-07', end_date: '2026-08-05', truncated: false },
}

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
  it('网格批次使用 P4 和采集时间展示并标记最新项', async () => {
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

  it('自定义趋势日期范围最多 90 天并同步到 URL', async () => {
    const wrapper = mountView()
    await flushPromises()
    vi.clearAllMocks()

    const rangeSelect = wrapper.findComponent('.days-select')
    await rangeSelect.vm.$emit('change', 'custom')
    expect(wrapper.find('.custom-range-picker').exists()).toBe(true)

    const rangePicker = wrapper.findComponent('.custom-range-picker')
    await rangePicker.vm.$emit('change', ['2026-05-01', '2026-08-01'])
    await flushPromises()
    expect(apiMock.mapBuildTrend).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('自定义日期范围最多 90 天')

    await rangePicker.vm.$emit('change', ['2026-06-01', '2026-08-29'])
    await flushPromises()

    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main',
      start_date: '2026-06-01',
      end_date: '2026-08-29',
      metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Coral_WP',
      query: {
        branch_tag: 'main', batch: '2', start: '2026-06-01', end: '2026-08-29', scope: 'self',
      },
    })
  })

  it('趋势筛选弹层不挂载到内部滚动容器', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent('.scene-select').attributes('popup-container'))
      .toBe('.map-build-page')
    expect(wrapper.findComponent('.days-select').attributes('popup-container')).toBeUndefined()

    await wrapper.findComponent('.days-select').vm.$emit('change', 'custom')
    expect(wrapper.findComponent('.custom-range-picker').attributes('popup-container'))
      .toBeUndefined()
  })

  it('刷新自定义日期 URL 后恢复日历范围', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = {
      batch: '1', start: '2026-07-01', end: '2026-08-05', scope: 'self',
    }
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: batch('1', '2026-08-04T10:00'),
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent('.days-select').props('modelValue')).toBe('custom')
    expect(wrapper.findComponent('.custom-range-picker').props('modelValue')).toEqual([
      '2026-07-01', '2026-08-05',
    ])
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      start_date: '2026-07-01',
      end_date: '2026-08-05',
      metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
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
    expect(mapBuildViewSource).toMatch(
      /\.atlas-card\.self-head-selected > \.world-head \{[^}]*border-top-left-radius: inherit; border-top-right-radius: inherit;/s,
    )
    expect(mapBuildViewSource).toMatch(
      /\.block-panel\.self-head-selected > \.block-head \{[^}]*border-top-left-radius: inherit; border-top-right-radius: inherit;/s,
    )
    expect(mapBuildViewSource).toMatch(
      /\.block-panel\.self-head-selected > \.block-head \{[^}]*box-shadow: inset 0 0 0 1px/s,
    )
    expect(mapBuildViewSource).toMatch(
      /\.block-panel\.self-head-selected > \.block-head \{[^}]*background: color-mix\(in srgb, rgb\(var\(--arcoblue-6\)\) 7%, transparent\)/s,
    )
    expect(mapBuildViewSource).toMatch(/\.block-panel \{[^}]*border-radius: 0;/s)
    expect(mapBuildViewSource).toMatch(/\.auxiliary-block \{[^}]*border-radius: 0;/s)
    expect(mapBuildViewSource).not.toContain('.block-panel.self-head-selected::after')

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
    const selectedRule = mapBuildViewSource.match(/\.sub-cell\.selected \{[^}]+\}/)?.[0]

    expect(mapBuildViewSource).not.toContain('.sub-cell::after')
    expect(mapBuildViewSource).toMatch(
      /\.sub-grid \{[^}]*gap: 0; background: transparent;/s,
    )
    expect(mapBuildViewSource).toMatch(
      /\.sub-cell:not\(:nth-child\(4n\)\) \{ border-right: 1px solid rgba\(0,0,0,\.26\); \}/,
    )
    expect(mapBuildViewSource).toMatch(
      /\.sub-cell:nth-child\(-n\+12\) \{ border-bottom: 1px solid rgba\(0,0,0,\.26\); \}/,
    )
    expect(mapBuildViewSource).toMatch(
      /\.sub-cell:hover \{[^}]*filter: brightness\(1\.07\);/s,
    )
    expect(selectedRule).toContain('box-shadow: inset 0 0 0 2px #91bdff;')
    expect(selectedRule?.match(/#91bdff/g)).toHaveLength(1)
    expect(mapBuildViewSource).not.toMatch(/\.sub-cell b \{[^}]*text-shadow:/s)
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
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main', days: 30, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(routerMock.replace).toHaveBeenLastCalledWith({
      path: '/map-build/Coral_WP',
      query: { branch_tag: 'main', batch: '2', days: '30', scope: 'self' },
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

  it('重新进入页面时选择最新批次并恢复分块、统计口径和趋势天数', async () => {
    routeMock.path = '/map-build/Coral_WP'
    routeMock.params.sceneId = 'Coral_WP'
    routeMock.query = {
      batch: '1', days: '14', scope: 'subtree', block: '3', sub: '1',
    }
    apiMock.mapBuildOverview.mockResolvedValueOnce({
      ...overview,
      batch: batch('1', '2026-08-04T10:00'),
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
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMock.mapBuildTrend).toHaveBeenCalledWith('Coral_WP', {
      branch_tag: 'main',
      days: 14,
      metric_scope: 'subtree',
      block_index: 3,
      sub_block_index: 1,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent('.batch-select').props('modelValue')).toBe('1')
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3 / 0x01（含子级汇总）')
    expect(wrapper.findComponent('.days-select').props('modelValue')).toBe(14)
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
        branch_tag: 'main', batch: '2', days: '30', scope: 'self', block: '3', sub: '1',
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
    apiMock.mapBuildTrend.mockRejectedValueOnce(new Error('trend temporarily unavailable'))
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
    apiMock.mapBuildOverview.mockImplementationOnce(pendingUntilAbort)
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
      path: '/map-build/Forest_WP', query: { branch_tag: 'main' },
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
      branch_tag: 'main', days: 30, metric_scope: 'subtree', block_index: 3,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))

    await wrapper.findAll('.sub-cell')[0].trigger('click')
    await flushPromises()
    expect(wrapper.get('.world-total small').text()).toBe('含子级汇总')
    expect(wrapper.get('.block-values small').text()).toBe('含子级汇总')
    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('含子级')
    expect(wrapper.get('.detail-head h3').text()).toBe('分块 3 / 0x00（含子级汇总）')
    expect(wrapper.find('.detail-eyebrow').exists()).toBe(false)
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', days: 30, metric_scope: 'subtree', block_index: 3, sub_block_index: 0,
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
      days: 30,
      metric_scope: 'self',
      registry_path: '/reflection',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))

    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.get('.auxiliary-block').text()).toBe('反射分块12.00 MiB')
    expect(wrapper.get('.detail-head h3').text()).toBe('反射分块')
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main',
      days: 30,
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
      branch_tag: 'main', days: 30, metric_scope: 'self',
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
    expect(wrapper.findAll('.detail-summary span').map((node) => node.text())).toEqual([
      '总 Mip', 'Cook 估算', '纹理数',
    ])
    expect(wrapper.get('.world-total small').text()).toBe('仅自身')
    expect(wrapper.get('.world-total b').attributes('title')).toBeTruthy()
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
      branch_tag: 'main', days: 30, metric_scope: 'self', block_index: 3,
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.get('.metric-scope-switch button[aria-pressed="true"]').text()).toBe('仅自身')

    apiMock.mapBuildTrend.mockResolvedValueOnce({
      selection: { label: '分块 3 · 含子级汇总' }, points: [],
    })
    await wrapper.findAll('.metric-scope-switch button')[1].trigger('click')
    await flushPromises()
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Coral_WP', {
      branch_tag: 'main', days: 30, metric_scope: 'subtree', block_index: 3,
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
      branch_tag: 'main', days: 30, metric_scope: 'subtree', block_index: 3, sub_block_index: 1,
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
    const staleTrend = deferred()
    const latestTrend = deferred()
    apiMock.mapBuildOverview
      .mockImplementationOnce(() => staleOverview.promise)
      .mockImplementationOnce(() => latestOverview.promise)
    apiMock.mapBuildTrend
      .mockImplementationOnce(() => staleTrend.promise)
      .mockImplementationOnce(() => latestTrend.promise)

    const sceneSelect = wrapper.findComponent('.scene-select')
    sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    sceneSelect.vm.$emit('change', 'Forest_WP')
    await Promise.resolve()
    const staleOverviewSignal = apiMock.mapBuildOverview.mock.calls.at(-1)[2].signal
    const staleTrendSignal = apiMock.mapBuildTrend.mock.calls.at(-1)[2].signal

    sceneSelect.vm.$emit('update:modelValue', 'Coral_WP')
    sceneSelect.vm.$emit('change', 'Coral_WP')
    await Promise.resolve()
    expect(staleOverviewSignal.aborted).toBe(true)
    expect(staleTrendSignal.aborted).toBe(true)

    latestOverview.resolve(overview)
    latestTrend.resolve(worldTrend)
    await flushPromises()
    expect(wrapper.get('.detail-head h3').text()).toBe('主分块')
    expect(wrapper.get('.selection-pill').text()).toBe('主分块 · 仅自身')

    staleOverview.resolve({
      ...overviewWithoutBlocks,
      batch: { ...batch('9', '2026-08-06T10:00'), scene_id: 'Forest_WP' },
    })
    staleTrend.resolve({ selection: { label: 'Forest 过期趋势' }, points: [] })
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
      branch_tag: 'main', days: 30, metric_scope: 'subtree',
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
    apiMock.mapBuildTrend
      .mockResolvedValueOnce({
        ...worldTrend,
        selection: { ...worldTrend.selection, metric_scope: 'subtree' },
      })
      .mockResolvedValueOnce(worldTrend)
    const sceneSelect = wrapper.findComponent('.scene-select')
    sceneSelect.vm.$emit('update:modelValue', 'Forest_WP')
    sceneSelect.vm.$emit('change', 'Forest_WP')
    await flushPromises()

    expect(wrapper.find('.metric-scope-switch').exists()).toBe(false)
    expect(apiMock.mapBuildTrend).toHaveBeenCalledTimes(2)
    expect(apiMock.mapBuildTrend).toHaveBeenLastCalledWith('Forest_WP', {
      branch_tag: 'main', days: 30, metric_scope: 'self',
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
      branch_tag: 'main', days: 30, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('点击趋势点会复用网格批次切换流程并更新当前批次', async () => {
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
      branch_tag: 'main', days: 30, metric_scope: 'self',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })
})
