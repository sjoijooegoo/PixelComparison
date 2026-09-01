// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const messageError = vi.hoisted(() => vi.fn())
let resolveApplyRoute

const storeMock = vi.hoisted(() => ({
  filters: {
    branchTag: 'main', platform: 'IOS', mapName: 'Forest_WP', shadingQuality: 1, batchId: 'batch-1',
  },
  metricKey: 'Scene_DC',
  trendMode: 'average',
  days: 14,
  frame: null,
  selectedPointId: null,
  selectedPoint: null,
  pointDetail: null,
  trends: null,
  scopeEmpty: false,
  loading: { meta: false, frame: false, detail: false, trends: false },
  errors: { meta: '', frame: '', detail: '', trends: '' },
  mapOptions: [],
  platformOptions: [],
  qualityOptions: [],
  batchOptions: [],
  mapHasBatches: vi.fn(() => true),
  qualityHasBatches: vi.fn(() => true),
  applyRoute: vi.fn(),
  changeScope: vi.fn(),
  selectPoint: vi.fn(),
  loadTrends: vi.fn(),
  changeTrendMode: vi.fn(),
  refresh: vi.fn(),
  dispose: vi.fn(),
  routeState: vi.fn(() => ({
    mapName: 'Forest_WP', platform: 'IOS', shadingQuality: 1, batchId: 'batch-1',
    metric: 'Scene_DC', point: null, trendMode: 'average', days: 14,
  })),
}))

vi.mock('@arco-design/web-vue', () => ({ Message: { error: messageError } }))
vi.mock('../stores/gpmHeatmapStore', () => ({ useGpmHeatmapStore: () => storeMock }))
vi.mock('../pageActions', () => ({ registerPageRefresh: vi.fn(() => vi.fn()) }))

import GpmHeatmapView from './GpmHeatmapView.vue'

const EmptyView = defineComponent({ template: '<div class="target-page" />' })
const AppView = defineComponent({ template: '<router-view />' })
const TrendStub = defineComponent({
  emits: ['select-batch'],
  template: '<button class="trend-stub" @click="$emit(\'select-batch\', \'batch-2\')" />',
})

async function flushRoute() {
  await Promise.resolve()
  await nextTick()
  await Promise.resolve()
}

describe('GpmHeatmapView route ownership', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    storeMock.frame = null
    storeMock.trends = null
    storeMock.filters.batchId = 'batch-1'
    storeMock.applyRoute.mockImplementation(() => new Promise((resolve) => {
      resolveApplyRoute = resolve
    }))
  })

  it('快速离页时不会让尚未完成的热力图初始化覆盖目标页面', async () => {
    let resolveTargetView
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/gpm-heatmap/:mapName?', component: GpmHeatmapView },
        {
          path: '/screenshot',
          component: () => new Promise((resolve) => {
            resolveTargetView = () => resolve(EmptyView)
          }),
        },
      ],
    })
    await router.push('/gpm-heatmap')
    await router.isReady()
    const replace = vi.spyOn(router, 'replace')
    const wrapper = mount(AppView, {
      global: {
        plugins: [router],
        stubs: {
          GpmDetailPanel: true,
          GpmMapCanvas: true,
          GpmScreenshotStrip: true,
          GpmTrendCard: true,
          'a-button': true,
          'a-empty': true,
          'a-option': true,
          'a-radio': true,
          'a-radio-group': true,
          'a-select': true,
          'a-spin': true,
        },
      },
    })
    await flushRoute()
    expect(storeMock.applyRoute).toHaveBeenCalledTimes(1)

    const leaving = router.push('/screenshot')
    await flushRoute()
    expect(storeMock.dispose).toHaveBeenCalledTimes(1)

    resolveApplyRoute()
    await flushRoute()
    expect(replace).not.toHaveBeenCalled()

    await vi.waitFor(() => expect(resolveTargetView).toBeTypeOf('function'))
    resolveTargetView()
    await leaving
    await flushRoute()
    expect(router.currentRoute.value.path).toBe('/screenshot')
    expect(wrapper.find('.target-page').exists()).toBe(true)
    expect(messageError).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('点击趋势节点后切换到对应采集批次', async () => {
    storeMock.frame = {
      heat_map: [], points: [], trend: [{ key: 'Scene_DC', name: '场景 DC' }],
    }
    storeMock.trends = {
      points: [{ batch_id: 'batch-2', captured_at: '2026-09-01T10:00:00+08:00' }],
    }
    storeMock.applyRoute.mockResolvedValue()
    storeMock.changeScope.mockResolvedValue()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/gpm-heatmap/:mapName?', component: GpmHeatmapView }],
    })
    await router.push('/gpm-heatmap/Forest_WP')
    await router.isReady()
    const wrapper = mount(AppView, {
      global: {
        plugins: [router],
        stubs: {
          GpmDetailPanel: true,
          GpmMapCanvas: true,
          GpmScreenshotStrip: true,
          GpmTrendCard: TrendStub,
          'a-button': true,
          'a-empty': true,
          'a-option': true,
          'a-radio': true,
          'a-radio-group': true,
          'a-select': true,
          'a-spin': true,
        },
      },
    })
    await flushRoute()

    await wrapper.get('.trend-stub').trigger('click')
    await flushRoute()

    expect(storeMock.changeScope).toHaveBeenCalledWith({ batchId: 'batch-2' })
    wrapper.unmount()
  })
})
