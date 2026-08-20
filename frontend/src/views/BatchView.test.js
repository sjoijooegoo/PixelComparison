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
    shading_quality: '',
    dateMode: 'range',
    created_from: '2026-08-14',
    created_to: '2026-08-20',
    created_dates: [],
  },
  batchPage: 1,
  batchLoading: false,
  initialized: false,
  applyRoute: vi.fn(async (requested) => {
    const quality = requested.shadingQuality === 'all' || requested.shadingQuality == null
      ? ''
      : Number(requested.shadingQuality)
    storeMock.filters = {
      branch_tag: requested.branchTag || 'main',
      scene_id: requested.sceneId || '',
      shading_quality: quality,
      dateMode: requested.dateMode || 'range',
      created_from: requested.createdFrom || '2026-08-14',
      created_to: requested.createdTo || '2026-08-20',
      created_dates: [...(requested.createdDates || [])],
    }
    storeMock.batchPage = Number(requested.page) || 1
    storeMock.initialized = true
    return {
      branchTag: storeMock.filters.branch_tag,
      sceneId: storeMock.filters.scene_id,
      shadingQuality: storeMock.filters.shading_quality,
      dateMode: storeMock.filters.dateMode,
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
      routes: [{ path: '/batches', component: BatchView }],
    })
    await router.push('/batches')
    await router.isReady()
    wrapper = mount(BatchView, {
      global: {
        plugins: [router],
        stubs: {
          FilterSidebar: EmptyStub,
          BatchTable: EmptyStub,
          'a-button': EmptyStub,
          'a-spin': EmptyStub,
        },
      },
    })
    await flushRoute()
  })

  it('无参数地址规范化为 main、全部场景和全部画质', () => {
    expect(storeMock.applyRoute).toHaveBeenCalledWith({
      branchTag: 'main',
      sceneId: '',
      shadingQuality: undefined,
      dateMode: undefined,
      createdFrom: undefined,
      createdTo: undefined,
      createdDates: [],
      page: undefined,
    })
    expect(router.currentRoute.value.query).toEqual({
      branch_tag: 'main',
      quality: 'all',
      date_mode: 'range',
      from: '2026-08-14',
      to: '2026-08-20',
    })
    wrapper.unmount()
  })

  it('路由变化时恢复筛选和页码', async () => {
    storeMock.applyRoute.mockClear()
    await router.push({
      path: '/batches',
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
      branchTag: 'engine-ue5',
      sceneId: 'SceneB',
      shadingQuality: '3',
      dateMode: 'days',
      createdFrom: undefined,
      createdTo: undefined,
      createdDates: ['2026-08-01', '2026-08-03'],
      page: '2',
    })
    expect(storeMock.filters).toMatchObject({
      branch_tag: 'engine-ue5',
      scene_id: 'SceneB',
      shading_quality: 3,
      dateMode: 'days',
    })
    expect(storeMock.batchPage).toBe(2)
    wrapper.unmount()
  })
})
