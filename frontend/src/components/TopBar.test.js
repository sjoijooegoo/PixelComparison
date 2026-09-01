// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routeMock = vi.hoisted(() => ({
  path: '/map-build/Coral_WP', fullPath: '/map-build/Coral_WP?branch_tag=engine-ue5',
  params: { sceneId: 'Coral_WP' }, query: { branch_tag: 'engine-ue5' },
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  resolve: vi.fn((target) => {
    const fullPath = typeof target === 'string' ? target : target.path
    const [path, queryText = ''] = fullPath.split('?')
    const query = Object.fromEntries(new URLSearchParams(queryText))
    const parts = path.split('/').filter(Boolean)
    return {
      path, fullPath, query,
      params: { sceneId: parts.length > 1 ? decodeURIComponent(parts[1]) : undefined },
    }
  }),
}))
const projectMock = vi.hoisted(() => ({
  uploadVisible: false,
  loadMeta: vi.fn(),
  meta: { scene_data_flags: {} },
}))
const screenshotMock = vi.hoisted(() => ({ running: false }))
const catalogMock = vi.hoisted(() => ({ filters: { branch_tag: 'engine-ue5' } }))
const messageMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))

vi.mock('vue-router', () => ({ useRoute: () => routeMock, useRouter: () => routerMock }))
vi.mock('../stores/projectStore', () => ({ useProjectStore: () => projectMock }))
vi.mock('../stores/screenshotComparisonStore', () => ({
  useScreenshotComparisonStore: () => screenshotMock,
}))
vi.mock('../stores/batchCatalogStore', () => ({ useBatchCatalogStore: () => catalogMock }))
vi.mock('@arco-design/web-vue', () => ({ Message: messageMock }))

import TopBar from './TopBar.vue'
import { registerPageRefresh } from '../pageActions'

const TooltipStub = defineComponent({ template: '<span><slot/></span>' })
const ConfigurationTransferStub = defineComponent({
  template: '<button aria-label="导入热力图配置"/><button aria-label="导出热力图配置"/>',
})

function setRoute(path, { query = {}, params = {}, fullPath = path } = {}) {
  routeMock.path = path
  routeMock.fullPath = fullPath
  routeMock.query = query
  routeMock.params = params
}

function mountTopBar() {
  return mount(TopBar, {
    global: { stubs: {
      'a-tooltip': TooltipStub,
      GpmConfigurationTransfer: ConfigurationTransferStub,
    } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  setRoute('/map-build/Coral_WP', {
    params: { sceneId: 'Coral_WP' }, query: { branch_tag: 'engine-ue5' },
    fullPath: '/map-build/Coral_WP?branch_tag=engine-ue5',
  })
  projectMock.uploadVisible = false
  projectMock.meta = { scene_data_flags: {} }
  projectMock.loadMeta.mockResolvedValue()
  screenshotMock.running = false
})

describe('TopBar contextual workspace tools', () => {
  it('主导航只保留三个工作区，烘培数据提供批次入口但不提供截图设置', () => {
    const wrapper = mountTopBar()

    expect(wrapper.findAll('.tab').map((tab) => tab.text())).toEqual([
      '截图对比', '烘培数据', '热力图',
    ])
    expect(wrapper.find('button[aria-label="批次管理"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="截图对比设置"]').exists()).toBe(false)
    expect(wrapper.find('.actions').findAll('button').map(
      (button) => button.attributes('aria-label'),
    )).toEqual(['刷新', '手动上报', '批次管理'])
    wrapper.unmount()
  })

  it('截图对比把批次管理和设置分别打开为携带完整来源的页面', async () => {
    setRoute('/screenshot/SceneA', {
      params: { sceneId: 'SceneA' }, query: { branch_tag: 'main', quality: '5' },
      fullPath: '/screenshot/SceneA?branch_tag=main&quality=5',
    })
    const wrapper = mountTopBar()

    await wrapper.get('button[aria-label="批次管理"]').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/batch-management/capture',
      query: { return_to: '/screenshot/SceneA?branch_tag=main&quality=5' },
    })
    await wrapper.get('button[aria-label="截图对比设置"]').trigger('click')
    expect(routerMock.push).toHaveBeenLastCalledWith({
      path: '/settings/screenshot-comparison',
      query: { return_to: '/screenshot/SceneA?branch_tag=main&quality=5' },
    })
    wrapper.unmount()
  })

  it('烘培数据保留刷新和手动上报', async () => {
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

  it('管理页使用来源工作区高亮，并从顶栏返回完整来源地址', async () => {
    setRoute('/batch-management/capture', {
      query: { return_to: '/map-build/SceneB?branch_tag=engine-ue5' },
      fullPath: '/batch-management/capture?return_to=source',
    })
    const wrapper = mountTopBar()

    expect(wrapper.findAll('.tab').find((tab) => tab.classes('active')).text()).toBe('烘培数据')
    expect(wrapper.find('button[aria-label="批次管理"]').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="手动上报"]').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="截图对比设置"]').exists()).toBe(false)
    expect(wrapper.find('.actions').findAll('button').map(
      (button) => button.attributes('aria-label'),
    )).toEqual(['返回烘培数据', '刷新'])
    await wrapper.get('button[aria-label="返回烘培数据"]').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith('/map-build/SceneB?branch_tag=engine-ue5')
    await wrapper.findAll('.tab').find((tab) => tab.text() === '烘培数据').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith('/map-build/SceneB?branch_tag=engine-ue5')
    wrapper.unmount()
  })

  it('热力图使用独立批次入口且不执行定时自动刷新', async () => {
    vi.useFakeTimers()
    setRoute('/gpm-heatmap/Village_Dimension_Main', {
      params: { sceneId: 'Village_Dimension_Main' }, query: { branch_tag: 'main' },
      fullPath: '/gpm-heatmap/Village_Dimension_Main?branch_tag=main',
    })
    const refreshPage = vi.fn().mockResolvedValue()
    const unregister = registerPageRefresh(refreshPage)
    const wrapper = mountTopBar()

    await wrapper.get('button[aria-label="批次管理"]').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/batch-management/gpm',
      query: { return_to: '/gpm-heatmap/Village_Dimension_Main?branch_tag=main' },
    })
    expect(wrapper.find('button[aria-label="手动上报"]').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="截图对比设置"]').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="热力图设置"]').exists()).toBe(true)
    await wrapper.get('button[aria-label="热力图设置"]').trigger('click')
    expect(routerMock.push).toHaveBeenLastCalledWith({
      path: '/settings/gpm-heatmap',
      query: { return_to: '/gpm-heatmap/Village_Dimension_Main?branch_tag=main' },
    })
    vi.advanceTimersByTime(240000)
    await flushPromises()
    expect(refreshPage).not.toHaveBeenCalled()
    expect(projectMock.loadMeta).not.toHaveBeenCalled()
    unregister()
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('截图设置页提供顶栏返回并保持截图对比高亮', async () => {
    setRoute('/settings/screenshot-comparison', {
      query: { return_to: '/screenshot/SceneA' },
      fullPath: '/settings/screenshot-comparison?return_to=/screenshot/SceneA',
    })
    const wrapper = mountTopBar()

    expect(wrapper.findAll('.tab').find((tab) => tab.classes('active')).text()).toBe('截图对比')
    expect(wrapper.find('.actions').findAll('button').map(
      (button) => button.attributes('aria-label'),
    )).toEqual(['返回截图对比'])
    await wrapper.get('button[aria-label="返回截图对比"]').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith('/screenshot/SceneA')
    wrapper.unmount()
  })

  it('热力图设置页提供顶栏返回并保持热力图高亮', async () => {
    setRoute('/settings/gpm-heatmap', {
      query: { return_to: '/gpm-heatmap/Village_Dimension_Main?batch=gpm-1' },
      fullPath: '/settings/gpm-heatmap?return_to=source',
    })
    const wrapper = mountTopBar()

    expect(wrapper.findAll('.tab').find((tab) => tab.classes('active')).text()).toBe('热力图')
    expect(wrapper.find('.actions').findAll('button').map(
      (button) => button.attributes('aria-label'),
    )).toEqual(['返回热力图', '导入热力图配置', '导出热力图配置'])
    await wrapper.get('button[aria-label="返回热力图"]').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith(
      '/gpm-heatmap/Village_Dimension_Main?batch=gpm-1',
    )
    wrapper.unmount()
  })

  it('工作区之间继续继承当前场景和分支', async () => {
    setRoute('/map-build/Volcano_WP', {
      params: { sceneId: 'Volcano_WP' }, query: { branch_tag: 'engine-ue5' },
      fullPath: '/map-build/Volcano_WP?branch_tag=engine-ue5',
    })
    const wrapper = mountTopBar()
    await wrapper.findAll('.tab').find((tab) => tab.text() === '截图对比').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/screenshot/Volcano_WP', query: { branch_tag: 'engine-ue5' },
    })
    wrapper.unmount()
  })

  it('从截图或烘培数据切回热力图时只传递当前场景', async () => {
    setRoute('/map-build/Volcano_WP', {
      params: { sceneId: 'Volcano_WP' },
      query: { branch_tag: 'engine-ue5', quality: '4', batch: 'capture-1' },
      fullPath: '/map-build/Volcano_WP?branch_tag=engine-ue5&quality=4&batch=capture-1',
    })
    const mapBuildWrapper = mountTopBar()
    await mapBuildWrapper.findAll('.tab').find((tab) => tab.text() === '热力图').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/gpm-heatmap/Volcano_WP',
    })
    mapBuildWrapper.unmount()

    vi.clearAllMocks()
    setRoute('/screenshot/Forest_WP', {
      params: { sceneId: 'Forest_WP' },
      query: { branch_tag: 'main', quality: '5', current: 'capture-2' },
      fullPath: '/screenshot/Forest_WP?branch_tag=main&quality=5&current=capture-2',
    })
    const screenshotWrapper = mountTopBar()
    await screenshotWrapper.findAll('.tab').find((tab) => tab.text() === '热力图').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/gpm-heatmap/Forest_WP',
    })
    screenshotWrapper.unmount()
  })

  it('不依赖通用元数据也会把当前场景交给热力图自行解析', async () => {
    setRoute('/screenshot/ScreenshotOnly', {
      params: { sceneId: 'ScreenshotOnly' }, query: { branch_tag: 'main' },
      fullPath: '/screenshot/ScreenshotOnly?branch_tag=main',
    })
    const wrapper = mountTopBar()

    await wrapper.findAll('.tab').find((tab) => tab.text() === '热力图').trigger('click')

    expect(routerMock.push).toHaveBeenCalledWith({ path: '/gpm-heatmap/ScreenshotOnly' })
    wrapper.unmount()
  })

  it('从热力图切换时只把目标工作区已有的同名场景带过去', async () => {
    projectMock.meta.scene_data_flags = {
      main: {
        Forest_WP: { has_screenshots: true, has_map_build_data: true },
      },
    }
    setRoute('/gpm-heatmap/Forest_WP', {
      params: { mapName: 'Forest_WP' },
      query: { platform: 'IOS', quality: '4', batch: 'gpm-1', point: '8' },
      fullPath: '/gpm-heatmap/Forest_WP?platform=IOS&quality=4&batch=gpm-1&point=8',
    })
    const wrapper = mountTopBar()

    await wrapper.findAll('.tab').find((tab) => tab.text() === '截图对比').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/screenshot/Forest_WP',
    })
    await wrapper.findAll('.tab').find((tab) => tab.text() === '烘培数据').trigger('click')
    expect(routerMock.push).toHaveBeenLastCalledWith({
      path: '/map-build/Forest_WP',
    })
    wrapper.unmount()
  })

  it('目标工作区没有同名场景时进入默认页', async () => {
    projectMock.meta.scene_data_flags = {
      main: {
        GpmOnly: { has_screenshots: false, has_map_build_data: false },
      },
    }
    setRoute('/gpm-heatmap/GpmOnly', {
      params: { mapName: 'GpmOnly' }, query: { platform: 'Android' },
      fullPath: '/gpm-heatmap/GpmOnly?platform=Android',
    })
    const wrapper = mountTopBar()

    await wrapper.findAll('.tab').find((tab) => tab.text() === '截图对比').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({ path: '/screenshot' })
    await wrapper.findAll('.tab').find((tab) => tab.text() === '烘培数据').trigger('click')
    expect(routerMock.push).toHaveBeenLastCalledWith({ path: '/map-build' })
    wrapper.unmount()
  })
})
