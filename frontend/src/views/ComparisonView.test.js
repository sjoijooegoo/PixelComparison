// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routeMock = vi.hoisted(() => ({
  path: '/comparison/999', params: { id: '999' }, query: { branch_tag: 'main' },
}))
const routerMock = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }))
const storeMock = vi.hoisted(() => ({
  filters: { branch_tag: 'main' },
  meta: { branch_tags: ['main', 'engine-ue5'], scene_ids: [] },
  comparisonFilters: { scene_id: '', status: '' },
  comparisons: [{ id: 7, branch_tag: 'main' }],
  selectedComparison: null,
  openComparisonById: vi.fn(),
  openComparison: vi.fn(),
  loadComparisons: vi.fn(),
  resumeComparisonData: vi.fn(),
  changeComparisonBranch: vi.fn(),
  applyComparisonFilters: vi.fn(),
  cancelComparisonDataRequests: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))
vi.mock('../store', () => ({ useStore: () => storeMock }))

import ComparisonView from './ComparisonView.vue'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

const SlotStub = defineComponent({ template: '<div><slot/></div>' })
const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<div class="select-stub"><slot/></div>',
})

function mountView() {
  return mount(ComparisonView, {
    global: {
      stubs: {
        'a-select': SelectStub,
        'a-option': SlotStub,
        'a-button': SlotStub,
        ResultSummary: SlotStub,
        SceneList: SlotStub,
        DetailView: SlotStub,
        MetricsPanel: SlotStub,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  routeMock.path = '/comparison/999'
  routeMock.params.id = '999'
  routeMock.query = { branch_tag: 'main' }
  storeMock.filters.branch_tag = 'main'
  storeMock.comparisons = [{ id: 7, branch_tag: 'main' }]
  storeMock.selectedComparison = null
  storeMock.openComparisonById.mockResolvedValue(false)
  storeMock.openComparison.mockImplementation(async (comparison) => {
    storeMock.selectedComparison = comparison
  })
  storeMock.changeComparisonBranch.mockImplementation(async (branchTag) => {
    storeMock.filters.branch_tag = branchTag
    storeMock.comparisons = [{ id: 8, branch_tag: branchTag }]
    storeMock.selectedComparison = storeMock.comparisons[0]
  })
  storeMock.applyComparisonFilters.mockResolvedValue()
  routerMock.replace.mockResolvedValue()
})

describe('ComparisonView route synchronization', () => {
  it('筛选分支中不存在的结果 ID 回退到首条结果并同步 URL', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(storeMock.openComparison).toHaveBeenCalledWith(storeMock.comparisons[0])
    expect(routerMock.replace).toHaveBeenCalledWith({
      path: '/comparison/7',
      query: { branch_tag: 'main' },
    })

    wrapper.unmount()
  })

  it('较早的深链请求晚返回时不会覆盖用户刚切换的分支和 URL', async () => {
    const pendingRoute = deferred()
    storeMock.openComparisonById.mockReturnValueOnce(pendingRoute.promise)
    const wrapper = mountView()
    await Promise.resolve()

    await wrapper.findAllComponents(SelectStub)[0].vm.$emit('change', 'engine-ue5')
    await flushPromises()
    expect(routerMock.replace).toHaveBeenCalledWith({
      path: '/comparison/8',
      query: { branch_tag: 'engine-ue5' },
    })

    pendingRoute.resolve(false)
    await flushPromises()

    expect(storeMock.openComparison).not.toHaveBeenCalled()
    expect(routerMock.replace).not.toHaveBeenCalledWith({
      path: '/comparison/7',
      query: { branch_tag: 'main' },
    })
    expect(storeMock.filters.branch_tag).toBe('engine-ue5')

    wrapper.unmount()
  })
})
