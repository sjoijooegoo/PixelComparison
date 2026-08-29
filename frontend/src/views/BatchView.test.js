// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const projectMock = vi.hoisted(() => ({
  initialized: true,
  initializing: false,
  initError: '',
  init: vi.fn().mockResolvedValue(undefined),
}))
const storeMock = vi.hoisted(() => ({
  filters: {
    branch_tag: 'main',
    scene_id: '',
    dateMode: 'range',
    rangeMode: 'rolling',
    created_from: '2026-08-14',
    created_to: '2026-08-20',
    created_dates: [],
  },
  batchPage: 1,
  batchLoading: false,
  initialized: false,
  applyRoute: vi.fn(async (requested) => {
    storeMock.filters = {
      branch_tag: requested.branchTag || 'main',
      scene_id: requested.sceneId || '',
      dateMode: requested.dateMode || 'range',
      rangeMode: requested.rangeMode || 'rolling',
      created_from: requested.createdFrom || '2026-08-14',
      created_to: requested.createdTo || '2026-08-20',
      created_dates: [...(requested.createdDates || [])],
    }
    storeMock.batchPage = Number(requested.page) || 1
    storeMock.initialized = true
    return {
      branchTag: storeMock.filters.branch_tag,
      sceneId: storeMock.filters.scene_id,
      dateMode: storeMock.filters.dateMode,
      rangeMode: storeMock.filters.rangeMode,
      createdFrom: storeMock.filters.created_from,
      createdTo: storeMock.filters.created_to,
      createdDates: [...storeMock.filters.created_dates],
      page: storeMock.batchPage,
    }
  }),
  refresh: vi.fn(),
  deactivate: vi.fn(),
}))

vi.mock('../stores/projectStore', () => ({ useProjectStore: () => projectMock }))
vi.mock('../stores/batchCatalogStore', () => ({ useBatchCatalogStore: () => storeMock }))
vi.mock('../pageActions', () => ({ registerPageRefresh: vi.fn(() => vi.fn()) }))

import BatchView from './BatchView.vue'

const EmptyStub = defineComponent({ template: '<div />' })

async function flushRoute() {
  await flushPromises()
  await nextTick()
  await flushPromises()
  await nextTick()
}

describe('BatchView route synchronization', () => {
  let router
  let wrapper

  beforeEach(async () => {
    vi.clearAllMocks()
    storeMock.initialized = false
    storeMock.batchPage = 1
    router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/batch-management/capture', component: BatchView }],
    })
    await router.push('/batch-management/capture')
    await router.isReady()
    wrapper = mount(BatchView, {
      global: {
        plugins: [router],
        stubs: {
          FilterSidebar: EmptyStub,
          BatchTable: EmptyStub,
          'a-button': EmptyStub,
          'a-spin': EmptyStub,
          'a-tooltip': EmptyStub,
        },
      },
    })
    await flushRoute()
  })

  it('无参数地址规范化为 main 和全部场景', () => {
    expect(storeMock.applyRoute).toHaveBeenCalledWith({
      returnTo: '',
      branchTag: 'main',
      sceneId: '',
      dateMode: undefined,
      rangeMode: undefined,
      createdFrom: undefined,
      createdTo: undefined,
      createdDates: [],
      page: undefined,
    })
    expect(router.currentRoute.value.query).toEqual({
      branch_tag: 'main',
      date_mode: 'range',
      range_mode: 'rolling',
    })
    wrapper.unmount()
  })

  it('路由变化时恢复筛选和页码', async () => {
    storeMock.applyRoute.mockClear()
    await router.push({
      path: '/batch-management/capture',
      query: {
        branch_tag: 'engine-ue5',
        scene_id: 'SceneB',
        quality: '3',
        date_mode: 'days',
        dates: '2026-08-01,2026-08-03',
        page: '2',
      },
    })
    await flushRoute()

    expect(storeMock.applyRoute).toHaveBeenCalledWith({
      returnTo: '',
      branchTag: 'engine-ue5',
      sceneId: 'SceneB',
      dateMode: 'days',
      rangeMode: undefined,
      createdFrom: undefined,
      createdTo: undefined,
      createdDates: ['2026-08-01', '2026-08-03'],
      page: '2',
    })
    expect(storeMock.filters).toMatchObject({
      branch_tag: 'engine-ue5',
      scene_id: 'SceneB',
      dateMode: 'days',
    })
    expect(router.currentRoute.value.query).not.toHaveProperty('quality')
    expect(storeMock.batchPage).toBe(2)
    wrapper.unmount()
  })
})
