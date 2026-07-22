// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const storeHolder = vi.hoisted(() => ({
  current: null,
  state: {
    filters: {
      scene_id: 'SceneA',
      shading_quality: 5,
      created_from: '2026-07-01',
      created_to: '2026-07-14',
      created_dates: [],
    },
    grid: {
      batches: [{
        id: '1', created_at: '2026-07-14 12:00:00', p4_version: 1,
        shading_quality_label: '电影', scene_id: 'SceneA',
      }],
      rows: [],
    },
    gridCollapsed: new Set(),
    gridHeatmaps: null,
    gridHeatmapLoading: false,
    gridHeatmapError: '',
    gridLoading: false,
    gridError: '',
    baselineBatch: null,
    currentBatch: null,
    running: false,
    canCompare: false,
    progress: { done: 0, total: 0 },
    loadGrid: vi.fn(),
    loadGridHeatmaps: vi.fn(),
    cancelGridHeatmapRequest: vi.fn(),
    clearRole: vi.fn(),
    setRole: vi.fn(),
    runComparison: vi.fn(),
    gotoGridComparison: vi.fn(),
  },
}))

vi.mock('../store', async () => {
  const { reactive } = await import('vue')
  storeHolder.current = reactive(storeHolder.state)
  return {
    useStore: () => storeHolder.current,
    p4Label: (value) => `P4 ${value}`,
  }
})
vi.mock('../api', () => ({ thumbUrl: (url) => url }))
vi.mock('./checkpointName', () => ({
  splitCheckpointName: (name) => ({ name, index: '' }),
}))

import BatchGrid from './BatchGrid.vue'

const storeMock = storeHolder.current
const SlotStub = defineComponent({ template: '<div><slot/></div>' })

beforeEach(() => {
  vi.clearAllMocks()
  storeMock.filters.scene_id = 'SceneA'
  storeMock.filters.shading_quality = 5
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  vi.stubGlobal('requestAnimationFrame', (callback) => setTimeout(callback, 0))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BatchGrid scene scrolling', () => {
  it('只有场景 ID 变化时将纵向滚动位置重置为顶部', async () => {
    const wrapper = mount(BatchGrid, {
      global: {
        stubs: {
          'a-empty': SlotStub,
          'a-button': SlotStub,
          'a-spin': SlotStub,
          'a-image-preview': SlotStub,
        },
      },
    })
    const scroller = wrapper.get('.grid-scroll').element
    scroller.scrollTop = 180

    storeMock.filters.shading_quality = 4
    await nextTick()
    expect(scroller.scrollTop).toBe(180)

    storeMock.filters.scene_id = 'SceneB'
    await nextTick()
    await nextTick()
    expect(scroller.scrollTop).toBe(0)

    wrapper.unmount()
  })
})
