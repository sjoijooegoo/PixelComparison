// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routeMock = vi.hoisted(() => ({
  path: '/map-build/Coral_WP', params: { sceneId: 'Coral_WP' }, query: { branch_tag: 'engine-ue5' },
}))
const routerMock = vi.hoisted(() => ({ push: vi.fn() }))
const projectMock = vi.hoisted(() => ({
  uploadVisible: false,
  loadMeta: vi.fn(),
}))
const screenshotMock = vi.hoisted(() => ({
  running: false,
}))
const catalogMock = vi.hoisted(() => ({
  filters: { branch_tag: 'engine-ue5' },
}))
const messageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))
vi.mock('../stores/projectStore', () => ({ useProjectStore: () => projectMock }))
vi.mock('../stores/screenshotComparisonStore', () => ({
  useScreenshotComparisonStore: () => screenshotMock,
}))
vi.mock('../stores/batchCatalogStore', () => ({ useBatchCatalogStore: () => catalogMock }))
vi.mock('../theme', async () => {
  const { ref } = await import('vue')
  return { theme: ref('dark'), toggleTheme: vi.fn() }
})
vi.mock('@arco-design/web-vue', () => ({ Message: messageMock }))

import TopBar from './TopBar.vue'
import { registerPageRefresh } from '../pageActions'

const TooltipStub = defineComponent({ template: '<span><slot/></span>' })

function mountTopBar() {
  return mount(TopBar, {
    global: { stubs: { 'a-tooltip': TooltipStub } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  routeMock.path = '/map-build/Coral_WP'
  routeMock.params.sceneId = 'Coral_WP'
  routeMock.query = { branch_tag: 'engine-ue5' }
  projectMock.uploadVisible = false
  projectMock.loadMeta.mockResolvedValue()
  screenshotMock.running = false
})

describe('TopBar map-build actions', () => {
  it('烘培数据页在右上角保留刷新和手动上报', async () => {
    const refreshPage = vi.fn().mockResolvedValue()
    const unregister = registerPageRefresh(refreshPage)
    const wrapper = mountTopBar()

    await wrapper.get('button[aria-label="刷新"]').trigger('click')
    await flushPromises()
    expect(refreshPage).toHaveBeenCalledWith({ silent: false })
    expect(messageMock.success).toHaveBeenCalledWith('已刷新')

    await wrapper.get('button[aria-label="手动上报"]').trigger('click')
    expect(projectMock.uploadVisible).toBe(true)

    unregister()
    wrapper.unmount()
  })

  it('项目设置页不显示数据操作按钮', () => {
    routeMock.path = '/settings'
    const wrapper = mountTopBar()

    expect(wrapper.find('button[aria-label="刷新"]').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="手动上报"]').exists()).toBe(false)

    wrapper.unmount()
  })

  it('烘培数据与截图对比之间继承当前场景和分支', async () => {
    routeMock.path = '/map-build/Volcano_WP'
    routeMock.params.sceneId = 'Volcano_WP'
    const wrapper = mountTopBar()

    await wrapper.findAll('.tab').find((tab) => tab.text() === '截图对比').trigger('click')

    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/screenshot/Volcano_WP',
      query: { branch_tag: 'engine-ue5' },
    })
    wrapper.unmount()
  })

  it('从批次管理直接进入截图对比时不擅自选择场景', async () => {
    routeMock.path = '/batches'
    routeMock.params.sceneId = undefined
    routeMock.query = {}
    const wrapper = mountTopBar()

    await wrapper.findAll('.tab').find((tab) => tab.text() === '截图对比').trigger('click')

    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/screenshot',
      query: { branch_tag: 'engine-ue5' },
    })
    wrapper.unmount()
  })

})
