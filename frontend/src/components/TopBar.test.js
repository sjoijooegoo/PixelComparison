// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routeMock = vi.hoisted(() => ({
  path: '/map-build/Coral_WP', params: { sceneId: 'Coral_WP' }, query: { branch_tag: 'engine-ue5' },
}))
const routerMock = vi.hoisted(() => ({ push: vi.fn() }))
const storeMock = vi.hoisted(() => ({
  uploadVisible: false,
  running: false,
  refreshBatches: vi.fn(),
  loadComparisons: vi.fn(),
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
vi.mock('../store', () => ({ useStore: () => storeMock }))
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
  storeMock.uploadVisible = false
  storeMock.running = false
  storeMock.refreshBatches.mockResolvedValue('')
  storeMock.loadComparisons.mockResolvedValue()
})

describe('TopBar map-build actions', () => {
  it('烘培数据页在右上角保留刷新和手动上报', async () => {
    const refreshPage = vi.fn().mockResolvedValue()
    const unregister = registerPageRefresh(refreshPage)
    const wrapper = mountTopBar()

    await wrapper.get('button[aria-label="刷新"]').trigger('click')
    await flushPromises()
    expect(refreshPage).toHaveBeenCalledWith({ silent: false })
    expect(storeMock.refreshBatches).not.toHaveBeenCalled()
    expect(messageMock.success).toHaveBeenCalledWith('已刷新')

    await wrapper.get('button[aria-label="手动上报"]').trigger('click')
    expect(storeMock.uploadVisible).toBe(true)

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

  it('从批次管理进入烘培数据时继承当前场景', async () => {
    routeMock.path = '/batches/Volcano_WP'
    routeMock.params.sceneId = 'Volcano_WP'
    const wrapper = mountTopBar()

    await wrapper.findAll('.tab').find((tab) => tab.text() === '烘培数据').trigger('click')

    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/map-build/Volcano_WP',
      query: { branch_tag: 'engine-ue5' },
    })
    wrapper.unmount()
  })

})
