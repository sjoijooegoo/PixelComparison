// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const projectMock = vi.hoisted(() => ({
  meta: { scene_data_flags: {} },
  init: vi.fn().mockResolvedValue(undefined),
}))
const storeMock = vi.hoisted(() => ({
  filters: { branch_tag: 'main', scene_id: 'SceneA' },
  grid: { total: 1, batches: [{ id: 'a' }], rows: [] },
  gridLoading: false,
  gridError: '',
  baselineBatch: null,
  currentBatch: null,
  initialized: true,
  applyRoute: vi.fn(async ({ branchTag, sceneId, baselineId, currentId }) => {
    storeMock.filters.branch_tag = branchTag
    storeMock.filters.scene_id = sceneId
    return { branchTag, sceneId, baselineId, currentId }
  }),
  refresh: vi.fn(),
  loadGridHeatmaps: vi.fn(),
  deactivate: vi.fn(),
}))

vi.mock('../stores/projectStore', () => ({ useProjectStore: () => projectMock }))
vi.mock('../stores/screenshotComparisonStore', () => ({
  useScreenshotComparisonStore: () => storeMock,
}))
vi.mock('../pageActions', () => ({ registerPageRefresh: vi.fn(() => vi.fn()) }))

import ScreenshotComparisonView from './ScreenshotComparisonView.vue'

const EmptyStub = defineComponent({ template: '<div />' })

async function flushRoute() {
  await Promise.resolve()
  await nextTick()
  await Promise.resolve()
}

describe('ScreenshotComparisonView route synchronization', () => {
  let router
  let wrapper

  beforeEach(async () => {
    vi.clearAllMocks()
    storeMock.filters.branch_tag = 'main'
    storeMock.filters.scene_id = 'SceneA'
    storeMock.baselineBatch = null
    storeMock.currentBatch = null
    storeMock.initialized = true
    router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/screenshot/:sceneId?', component: ScreenshotComparisonView }],
    })
    await router.push('/screenshot/SceneA?branch_tag=main')
    await router.isReady()
    wrapper = mount(ScreenshotComparisonView, {
      global: {
        plugins: [router],
        stubs: {
          ScreenshotFilters: EmptyStub,
          BatchGrid: EmptyStub,
          'a-button': EmptyStub,
          'a-spin': EmptyStub,
        },
      },
    })
    await flushRoute()
    storeMock.applyRoute.mockClear()
  })

  it('下拉框先改 store 后切换场景，仍立即按新路由重新加载', async () => {
    // Arco Select 的 v-model 会在 router.push 前先写入当前 store。
    storeMock.filters.scene_id = 'SceneB'
    await router.push('/screenshot/SceneB?branch_tag=main')
    await flushRoute()

    expect(storeMock.applyRoute).toHaveBeenCalledTimes(1)
    expect(storeMock.applyRoute).toHaveBeenCalledWith({
      branchTag: 'main', sceneId: 'SceneB', baselineId: '', currentId: '',
      shadingQuality: undefined,
      dateMode: undefined,
      createdFrom: undefined,
      createdTo: undefined,
      createdDates: [],
    })
    expect(wrapper.find('h3').exists()).toBe(false)
    expect(wrapper.find('.screenshot-panel').classes()).not.toContain('card')
    wrapper.unmount()
  })

  it('把画质和连续日期查询参数交给 store 恢复', async () => {
    await router.push(
      '/screenshot/SceneB?branch_tag=main&quality=3&date_mode=range&from=2026-08-01&to=2026-08-07',
    )
    await flushRoute()

    expect(storeMock.applyRoute).toHaveBeenCalledWith({
      branchTag: 'main', sceneId: 'SceneB', baselineId: '', currentId: '',
      shadingQuality: '3',
      dateMode: 'range',
      createdFrom: '2026-08-01',
      createdTo: '2026-08-07',
      createdDates: [],
    })
    wrapper.unmount()
  })

  it('项目初始化未完成时离开页面不会继续恢复隐藏工作区', async () => {
    wrapper.unmount()
    storeMock.applyRoute.mockClear()
    let resolveInit
    projectMock.init.mockImplementationOnce(() => new Promise((resolve) => {
      resolveInit = resolve
    }))
    wrapper = mount(ScreenshotComparisonView, {
      global: {
        plugins: [router],
        stubs: {
          ScreenshotFilters: EmptyStub,
          BatchGrid: EmptyStub,
          'a-button': EmptyStub,
          'a-spin': EmptyStub,
        },
      },
    })
    await Promise.resolve()

    wrapper.unmount()
    resolveInit()
    await flushRoute()

    expect(storeMock.applyRoute).not.toHaveBeenCalled()
  })
})
