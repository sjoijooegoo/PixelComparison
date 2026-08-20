// @vitest-environment happy-dom
import { defineComponent, nextTick, ref } from 'vue'
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
        id: '1', column_id: '1:5', shading_quality: 5, created_at: '2026-07-14 12:00:00', p4_version: 1,
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
  },
}))

const messageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}))

vi.mock('../store', async () => {
  return {
    p4Label: (value) => `P4 ${value}`,
  }
})
vi.mock('../stores/screenshotComparisonStore', async () => {
  const { reactive } = await import('vue')
  storeHolder.current = reactive(storeHolder.state)
  return { useScreenshotComparisonStore: () => storeHolder.current }
})
vi.mock('../api', () => ({ thumbUrl: (url) => url }))
vi.mock('@arco-design/web-vue', () => ({ Message: messageMock }))
vi.mock('./checkpointName', () => ({
  splitCheckpointName: (name) => ({ name, index: '' }),
}))

import BatchGrid from './BatchGrid.vue'

const storeMock = storeHolder.current
const SlotStub = defineComponent({ template: '<div><slot/></div>' })
let wrapper
let imageRequests
let resizeCallbacks

class ControlledImage {
  constructor() {
    this.onload = null
    this.onerror = null
    this.decoding = ''
    this.src = ''
    this.cancelled = false
    imageRequests.push(this)
  }

  resolve() {
    this.onload?.()
  }

  reject() {
    this.onerror?.()
  }

  removeAttribute(name) {
    if (name === 'src') {
      this.src = ''
      this.cancelled = true
    }
  }
}

function defaultGrid() {
  return {
    batches: [{
      id: '1', column_id: '1:5', shading_quality: 5, created_at: '2026-07-14 12:00:00', p4_version: 1,
      shading_quality_label: '电影', scene_id: 'SceneA',
    }],
    rows: [],
  }
}

function previewGrid() {
  return {
    batches: ['1', '2', '3'].map((id) => ({
      id, column_id: `${id}:5`, shading_quality: 5, created_at: '2026-07-14 12:00:00', p4_version: 1,
      shading_quality_label: '电影', scene_id: 'SceneA',
    })),
    rows: [
      { scene_name: 'Up', cells: ['/images/up-left.png', '/images/up.png', '/images/up-right.png'] },
      { scene_name: 'Middle', cells: ['/images/left.png', '/images/current.png', '/images/right.png'] },
      { scene_name: 'Down', cells: ['/images/down-left.png', '/images/down.png', '/images/down-right.png'] },
    ],
  }
}

function mountGrid() {
  wrapper = mount(BatchGrid, {
    global: {
      stubs: {
        'a-empty': SlotStub,
        'a-button': SlotStub,
        'a-spin': SlotStub,
        'a-image-preview': SlotStub,
      },
    },
  })
  return wrapper
}

function mountKeptGrid() {
  const Host = defineComponent({
    components: { BatchGrid },
    setup() {
      return { show: ref(true) }
    },
    template: '<keep-alive><BatchGrid v-if="show" /></keep-alive>',
  })
  wrapper = mount(Host, {
    global: {
      stubs: {
        'a-empty': SlotStub,
        'a-button': SlotStub,
        'a-spin': SlotStub,
        'a-image-preview': SlotStub,
      },
    },
  })
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  imageRequests = []
  resizeCallbacks = []
  storeMock.filters.scene_id = 'SceneA'
  storeMock.filters.shading_quality = 5
  storeMock.grid = defaultGrid()
  storeMock.gridCollapsed = new Set()
  storeMock.gridHeatmaps = null
  storeMock.baselineBatch = null
  storeMock.currentBatch = null
  storeMock.running = false
  storeMock.canCompare = false
  vi.stubGlobal('devicePixelRatio', 1)
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback) { resizeCallbacks.push(callback) }
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  vi.stubGlobal('requestAnimationFrame', (callback) => setTimeout(callback, 0))
  vi.stubGlobal('Image', ControlledImage)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('BatchGrid scene scrolling', () => {
  it('只有场景 ID 变化时将纵向滚动位置重置为顶部', async () => {
    mountGrid()
    const scroller = wrapper.get('.grid-scroll').element
    scroller.scrollTop = 180

    storeMock.filters.shading_quality = 4
    await nextTick()
    expect(scroller.scrollTop).toBe(180)

    storeMock.filters.scene_id = 'SceneB'
    await nextTick()
    await nextTick()
    expect(scroller.scrollTop).toBe(0)
  })
})

describe('BatchGrid column sizing', () => {
  it('窗口化时保持全屏列宽，浏览器缩放时交给页面自然缩放', async () => {
    mountGrid()
    const scroller = wrapper.get('.grid-scroll').element
    Object.defineProperty(scroller, 'clientWidth', { configurable: true, value: 1700 })

    resizeCallbacks.forEach((callback) => callback())
    await nextTick()
    expect(wrapper.get('.matrix').attributes('style')).toContain('100px 200px 200px')

    Object.defineProperty(scroller, 'clientWidth', { configurable: true, value: 1300 })
    resizeCallbacks.forEach((callback) => callback())
    await nextTick()
    expect(wrapper.get('.matrix').attributes('style')).toContain('100px 200px 200px')

    vi.stubGlobal('devicePixelRatio', 1.25)
    Object.defineProperty(scroller, 'clientWidth', { configurable: true, value: 1360 })
    resizeCallbacks.forEach((callback) => callback())
    await nextTick()
    expect(wrapper.get('.matrix').attributes('style')).toContain('100px 200px 200px')
  })
})

describe('BatchGrid comparison feedback', () => {
  it('网格组件只展示 store 结果，不额外发起 lookup', async () => {
    mountGrid()
    storeMock.baselineBatch = { ...defaultGrid().batches[0], id: 'base' }
    storeMock.currentBatch = { ...defaultGrid().batches[0], id: 'current' }
    await nextTick()

    expect(storeMock.loadGridHeatmaps).not.toHaveBeenCalled()
  })

  it('对比在用户切换角色后被取消时不误报完成', async () => {
    const baseline = { ...defaultGrid().batches[0], id: '1' }
    const current = { ...defaultGrid().batches[0], id: '2', column_id: '2:5' }
    storeMock.grid = { batches: [baseline, current], rows: [] }
    storeMock.baselineBatch = baseline
    storeMock.currentBatch = current
    storeMock.canCompare = true
    storeMock.gridHeatmaps = {
      baseline_id: '1', current_id: '2', baseline_column_id: '1:5', current_column_id: '2:5',
      exists: false, ready: false, status: 'missing', map: {},
    }
    storeMock.runComparison.mockResolvedValue(null)
    mountGrid()

    await wrapper.get('.heat-title.is-btn > div').trigger('click')
    await Promise.resolve()

    expect(storeMock.runComparison).toHaveBeenCalledWith({ force: false })
    expect(messageMock.success).not.toHaveBeenCalled()
  })
})

describe('BatchGrid original image preloading', () => {
  it('当前原图完成后才以最多两个并发按左右上下预加载相邻原图', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    expect(imageRequests.map((image) => image.src)).toEqual(['/images/current.png'])

    imageRequests[0].resolve()
    expect(imageRequests.map((image) => image.src)).toEqual([
      '/images/current.png',
      '/images/left.png',
      '/images/right.png',
    ])

    imageRequests[1].resolve()
    expect(imageRequests.at(-1).src).toBe('/images/up.png')
    imageRequests[2].resolve()
    expect(imageRequests.at(-1).src).toBe('/images/down.png')
  })

  it('跳过空格和折叠列，并对四个方向的相同 URL 去重', async () => {
    const grid = previewGrid()
    grid.rows[0].cells[1] = ''
    grid.rows[2].cells[1] = '/images/right.png'
    storeMock.grid = grid
    storeMock.gridCollapsed = new Set(['1:5'])
    mountGrid()

    const currentThumb = wrapper.findAll('.thumb').find((node) => node.attributes('src') === '/images/current.png')
    await currentThumb.trigger('click')
    await nextTick()
    imageRequests[0].resolve()

    expect(imageRequests.map((image) => image.src)).toEqual([
      '/images/current.png',
      '/images/right.png',
    ])
  })

  it('当前原图加载失败时不继续请求相邻原图', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].reject()

    expect(imageRequests).toHaveLength(1)
  })

  it('当前原图探针长期无响应时会超时停止，不启动相邻预加载', async () => {
    vi.useFakeTimers()
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    vi.advanceTimersByTime(30_000)

    expect(imageRequests).toHaveLength(1)
    expect(imageRequests[0].cancelled).toBe(true)
  })

  it('相邻原图长期无响应时释放并发槽并继续后续队列', async () => {
    vi.useFakeTimers()
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].resolve()
    const hungNeighbors = imageRequests.slice(1)
    vi.advanceTimersByTime(30_000)

    expect(hungNeighbors.every((image) => image.cancelled)).toBe(true)
    expect(imageRequests.map((image) => image.src)).toContain('/images/up.png')
    expect(imageRequests.map((image) => image.src)).toContain('/images/down.png')
  })

  it('快速切换大图时用新位置的相邻图片替换旧等待队列', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].resolve()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await nextTick()
    expect(imageRequests.filter((image) => image.src === '/images/right.png')).toHaveLength(1)

    imageRequests[2].resolve()
    await Promise.resolve()
    imageRequests[1].resolve()
    expect(imageRequests.map((image) => image.src)).toContain('/images/up-right.png')
    expect(imageRequests.map((image) => image.src)).not.toContain('/images/up.png')
    expect(imageRequests.map((image) => image.src)).not.toContain('/images/down.png')
  })

  it('切换场景后取消当前探针和后台相邻图，不再推进队列', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].resolve()
    const activeNeighbors = imageRequests.slice(1)

    storeMock.filters.scene_id = 'SceneB'
    await nextTick()
    expect(activeNeighbors.every((image) => image.cancelled)).toBe(true)

    storeMock.grid = previewGrid()
    await nextTick()
    expect(imageRequests).toHaveLength(3)

    activeNeighbors.forEach((image) => image.resolve())
    expect(imageRequests).toHaveLength(3)
  })

  it('关闭大图后取消后台相邻图，不再推进队列', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].resolve()
    const activeNeighbors = imageRequests.slice(1)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(activeNeighbors.every((image) => image.cancelled)).toBe(true)

    activeNeighbors.forEach((image) => image.resolve())
    expect(imageRequests).toHaveLength(3)
  })

  it('组件卸载后取消后台相邻图，不再推进队列', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].resolve()
    const activeNeighbors = imageRequests.slice(1)

    wrapper.unmount()
    wrapper = null
    expect(activeNeighbors.every((image) => image.cancelled)).toBe(true)

    activeNeighbors.forEach((image) => image.resolve())
    expect(imageRequests).toHaveLength(3)
  })

  it('keep-alive 离开批次页面时关闭大图并停止后台预加载', async () => {
    storeMock.grid = previewGrid()
    mountKeptGrid()

    await wrapper.findAll('.thumb')[4].trigger('click')
    await nextTick()
    imageRequests[0].resolve()
    const activeNeighbors = imageRequests.slice(1)

    wrapper.vm.show = false
    await nextTick()
    expect(activeNeighbors.every((image) => image.cancelled)).toBe(true)

    activeNeighbors.forEach((image) => image.resolve())
    expect(imageRequests).toHaveLength(3)
  })

  it('从热力图大图按左右上下规则预加载有效相邻图片', async () => {
    storeMock.grid = previewGrid()
    storeMock.baselineBatch = storeMock.grid.batches[0]
    storeMock.currentBatch = storeMock.grid.batches[1]
    storeMock.gridHeatmaps = {
      baseline_id: '1',
      current_id: '2',
      baseline_column_id: '1:5',
      current_column_id: '2:5',
      exists: true,
      ready: true,
      status: 'done',
      map: {
        Up: '/heat/up.png',
        Middle: '/heat/middle.png',
        Down: '/heat/down.png',
      },
    }
    mountGrid()

    const heatThumb = wrapper.findAll('.thumb').find((node) => node.attributes('src') === '/heat/middle.png')
    await heatThumb.trigger('click')
    await nextTick()
    imageRequests[0].resolve()

    expect(imageRequests.map((image) => image.src)).toEqual([
      '/heat/middle.png',
      '/images/right.png',
      '/heat/up.png',
    ])
    imageRequests[1].resolve()
    expect(imageRequests.at(-1).src).toBe('/heat/down.png')
  })

  it('不存在热力图时不会把虚拟列作为预加载目标', async () => {
    storeMock.grid = previewGrid()
    mountGrid()

    const rightThumb = wrapper.findAll('.thumb').find((node) => node.attributes('src') === '/images/right.png')
    await rightThumb.trigger('click')
    await nextTick()
    imageRequests[0].resolve()

    expect(imageRequests.map((image) => image.src)).toEqual([
      '/images/right.png',
      '/images/current.png',
      '/images/up-right.png',
    ])
    imageRequests[1].resolve()
    expect(imageRequests.at(-1).src).toBe('/images/down-right.png')
    expect(imageRequests.some((image) => image.src.startsWith('/heat/'))).toBe(false)
  })
})
