// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({ gpmHeatmapCatalog: vi.fn(), gpmHeatmapUploads: vi.fn() }))
vi.mock('../api', () => ({ api: apiMock }))
import GpmBatchView from './GpmBatchView.vue'
import { useGpmBatchStore } from '../stores/gpmBatchStore'

const Empty = defineComponent({ template: '<div />' })
const Shell = defineComponent({ template: '<router-view />' })

async function flushRoute() {
  await flushPromises()
  await nextTick()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.gpmHeatmapCatalog.mockResolvedValue({ branch_tags: ['main'], maps: [], platforms: [] })
  apiMock.gpmHeatmapUploads.mockImplementation(async (params) => ({
    items: [{ id: 1, batch_id: 'source', branch_tag: 'main' }], total: 40,
    page: params.locate_batch_id ? Math.floor(25 / params.page_size) + 1 : params.page,
    located_batch_id: params.locate_batch_id || null,
  }))
})

async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/batch-management/gpm', component: GpmBatchView },
    { path: '/elsewhere', component: Empty },
  ] })
  await router.push('/batch-management/gpm?focus_batch=source')
  await router.isReady()
  const wrapper = mount(Shell, { global: {
    plugins: [pinia, router], stubs: { GpmBatchFilters: Empty, GpmBatchTable: Empty },
  } })
  await flushRoute()
  return { router, wrapper, store: useGpmBatchStore() }
}

describe('GpmBatchView 定位路由', () => {
  it('同步实际页码，窗口变化继续定位，手动翻页后不拉回来源', async () => {
    const { router, wrapper, store } = await setup()
    expect(router.currentRoute.value.query).toMatchObject({ focus_batch: 'source', page: '3' })
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledTimes(1)
    store.batchPageSize = 5
    await store.loadBatches()
    await flushRoute()
    expect(router.currentRoute.value.query.page).toBe('6')
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledTimes(2)
    await router.push({ path: '/batch-management/gpm', query: { branch_tag: 'main', page: '7' } })
    await flushRoute()
    expect(router.currentRoute.value.query.page).toBe('7')
    expect(router.currentRoute.value.query.focus_batch).toBeUndefined()
    expect(store.focusBatchId).toBe('')
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('离开页面后迟到的定位响应不能导航回来', async () => {
    const { router, wrapper, store } = await setup()
    let resolve
    apiMock.gpmHeatmapUploads.mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const pending = store.loadBatches()
    await router.push('/elsewhere')
    resolve({ items: [], page: 8, located_batch_id: 'source' })
    await pending
    await flushRoute()
    expect(router.currentRoute.value.path).toBe('/elsewhere')
    expect(store.batchPage).toBe(3)
    wrapper.unmount()
  })
})
