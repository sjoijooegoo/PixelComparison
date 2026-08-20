// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  batches: vi.fn(),
  createBatch: vi.fn(),
  uploadMapBuildData: vi.fn(),
  uploadScreenshot: vi.fn(),
  uploadQualityScreenshot: vi.fn(),
  autoCompare: vi.fn(),
}))
const messageMock = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../store', () => ({ p4Label: (value) => value == null ? '—' : `P4 ${value}` }))
vi.mock('@arco-design/web-vue', () => ({
  Message: messageMock,
  Modal: { confirm: vi.fn() },
}))

import ManualUpload from './ManualUpload.vue'

const SlotStub = defineComponent({ template: '<div><slot/></div>' })
const DescriptionsStub = defineComponent({
  props: ['data'],
  template: '<div><div v-for="item in data" :key="item.label"><slot name="value" :data="item"/></div></div>',
})
const ModalStub = defineComponent({
  template: '<section><header><slot name="title"/></header><slot/></section>',
})
const ButtonStub = defineComponent({
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot/></button>',
})

function packageFile(relativePath, content, type = 'application/octet-stream') {
  const name = relativePath.split('/').at(-1)
  const result = new File([content], name, { type })
  Object.defineProperty(result, 'webkitRelativePath', {
    configurable: true,
    value: `Package/${relativePath}`,
  })
  return result
}

function mountUpload() {
  return mount(ManualUpload, {
    props: { visible: true },
    global: {
      stubs: {
        'a-modal': ModalStub,
        'a-button': ButtonStub,
        'a-alert': SlotStub,
        'a-descriptions': DescriptionsStub,
        'a-input-number': SlotStub,
        'a-checkbox': SlotStub,
        'a-progress': SlotStub,
      },
    },
  })
}

describe('ManualUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.batches.mockResolvedValue({ items: [] })
    apiMock.createBatch.mockResolvedValue({ id: '77' })
    apiMock.uploadMapBuildData.mockResolvedValue({ registry_count: 1 })
    apiMock.uploadScreenshot.mockResolvedValue({ id: 1 })
    apiMock.uploadQualityScreenshot.mockResolvedValue({ id: 1 })
    apiMock.autoCompare.mockResolvedValue({ matched: false })
  })

  it('烘培数据上报失败时仍完成原有截图上报并明确提示部分失败', async () => {
    const manifest = {
      ue_data: { world_name: 'Coral_WP', platform: 'WindowsEditor', p4_version: 123 },
      screenshots: [{ name: 'Seq_Coral_0000', image: 'Screenshot/shot.png', index: 0 }],
      artifacts: {
        map_build_data: {
          path: 'Artifacts/map_build_data.json',
          format: 'map-build-data/v2',
        },
      },
    }
    const files = [
      packageFile('manifest.json', JSON.stringify(manifest), 'application/json'),
      packageFile('Screenshot/shot.png', 'png', 'image/png'),
      packageFile(
        'Artifacts/map_build_data.json',
        JSON.stringify({ worldAggregate: {}, registries: [{ path: '/root' }] }),
        'application/json',
      ),
    ]
    const wrapper = mountUpload()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('烘培数据 · 1 个 Registry')
    apiMock.uploadMapBuildData.mockRejectedValueOnce(
      Object.assign(new Error('invalid map build payload'), { status: 422 }),
    )
    const start = wrapper.findAll('button').find((button) => button.text() === '开始上报')
    expect(start).toBeTruthy()
    await start.trigger('click')
    await flushPromises()

    expect(apiMock.createBatch).toHaveBeenCalledWith(expect.objectContaining({
      scene_id: 'Coral_WP',
      platform: 'WindowsEditor',
    }))
    expect(apiMock.uploadMapBuildData).toHaveBeenCalledWith(
      '77',
      expect.objectContaining({ registries: [{ path: '/root' }] }),
      'map-build-data/v2',
      'main',
    )
    expect(apiMock.uploadQualityScreenshot).toHaveBeenCalledTimes(1)
    expect(messageMock.warning).toHaveBeenCalledWith('批次 #77 上报完成，但烘培数据失败')
    expect(wrapper.emitted('done')).toHaveLength(1)
    expect(wrapper.emitted('update:visible')).toContainEqual([false])
  })

  it('接受 engine-ue5 分支的纯烘培数据包且不会发起截图上传或自动对比', async () => {
    const manifest = {
      pipeline_data: { id: 'engine-77', branch_tag: ' Engine-UE5 ' },
      ue_data: { world_name: 'Coral_WP', platform: 'WindowsEditor', p4_version: 456 },
      artifacts: {
        map_build_data: {
          path: 'Artifacts/map_build_data.json',
          format: 'map-build-data/v2',
        },
      },
    }
    const files = [
      packageFile('manifest.json', JSON.stringify(manifest), 'application/json'),
      packageFile(
        'Artifacts/map_build_data.json',
        JSON.stringify({ worldAggregate: {}, registries: [{ path: '/root' }] }),
        'application/json',
      ),
    ]
    const wrapper = mountUpload()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('engine-ue5')
    expect(wrapper.text()).toContain('共 0 张截图')
    const start = wrapper.findAll('button').find((button) => button.text() === '开始上报')
    await start.trigger('click')
    await flushPromises()

    expect(apiMock.createBatch).toHaveBeenCalledWith(expect.objectContaining({
      branch_tag: 'engine-ue5',
    }))
    expect(apiMock.uploadMapBuildData).toHaveBeenCalledWith(
      '77',
      expect.any(Object),
      'map-build-data/v2',
      'engine-ue5',
    )
    expect(apiMock.uploadScreenshot).not.toHaveBeenCalled()
    expect(apiMock.uploadQualityScreenshot).not.toHaveBeenCalled()
    expect(apiMock.autoCompare).not.toHaveBeenCalled()
  })

  it('没有截图也没有烘培数据时拒绝进入上报预览', async () => {
    const manifest = {
      pipeline_data: { branch_tag: 'main' },
      ue_data: { world_name: 'Coral_WP', platform: 'WindowsEditor' },
    }
    const files = [packageFile('manifest.json', JSON.stringify(manifest), 'application/json')]
    const wrapper = mountUpload()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('数据包内既没有可上传的截图，也没有烘培数据')
    expect(wrapper.findAll('button').some((button) => button.text() === '开始上报')).toBe(false)
  })

  it('按 v2 画质运行原子建计划并上传到显式画质接口', async () => {
    const manifest = {
      format_version: 2,
      pipeline_data: { id: 'multi-1', branch_tag: 'main' },
      ue_data: {
        world_name: 'Coral_WP', platform: 'WindowsEditor',
        tex_quality_levels: [0, 2],
      },
      quality_runs: [
        {
          quality_run_index: 0, shading_quality: 5, tex_quality: 0,
          status: 'complete', screenshot_count: 1,
          screenshots: [{ name: 'Shot', image: 'Screenshot/0/Shot.png', index: 0 }],
        },
        {
          quality_run_index: 1, shading_quality: 3, tex_quality: 2,
          status: 'complete', screenshot_count: 1,
          screenshots: [{ name: 'Shot', image: 'Screenshot/1/Shot.png', index: 0 }],
        },
      ],
    }
    const files = [
      packageFile('manifest.json', JSON.stringify(manifest), 'application/json'),
      packageFile('Screenshot/0/Shot.png', 'movie', 'image/png'),
      packageFile('Screenshot/1/Shot.png', 'pretty', 'image/png'),
    ]
    const wrapper = mountUpload()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('电影 / 精美')
    const start = wrapper.findAll('button').find((button) => button.text() === '开始上报')
    await start.trigger('click')
    await flushPromises()

    expect(apiMock.createBatch).toHaveBeenCalledWith(expect.objectContaining({
      manifest_format_version: 2,
      quality_runs: [
        expect.objectContaining({ shading_quality: 5, tex_quality: 0 }),
        expect.objectContaining({ shading_quality: 3, tex_quality: 2 }),
      ],
    }))
    expect(apiMock.uploadQualityScreenshot).toHaveBeenCalledTimes(2)
    expect(apiMock.uploadQualityScreenshot.mock.calls.map((call) => call[1])).toEqual([5, 3])
  })

  it('v2 数据包缺图时在创建批次前失败', async () => {
    const manifest = {
      format_version: 2,
      ue_data: { world_name: 'Coral_WP', platform: 'WindowsEditor' },
      quality_runs: [{
        quality_run_index: 0, shading_quality: 5, tex_quality: 0,
        status: 'complete', screenshot_count: 1,
        screenshots: [{ name: 'Shot', image: 'Screenshot/0/missing.png', index: 0 }],
      }],
    }
    const files = [packageFile('manifest.json', JSON.stringify(manifest), 'application/json')]
    const wrapper = mountUpload()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('拒绝创建不完整批次')
    expect(apiMock.createBatch).not.toHaveBeenCalled()
  })

  it('同号批次未勾选覆盖时不会继续补传', async () => {
    apiMock.batches.mockResolvedValueOnce({ items: [{ id: 'dup' }] })
    const manifest = {
      pipeline_data: { id: 'dup', branch_tag: 'main' },
      ue_data: { world_name: 'Coral_WP', platform: 'WindowsEditor' },
      artifacts: {
        map_build_data: { path: 'map.json', format: 'map-build-data/v2' },
      },
    }
    const files = [
      packageFile('manifest.json', JSON.stringify(manifest), 'application/json'),
      packageFile('map.json', JSON.stringify({ worldAggregate: {}, registries: [] }), 'application/json'),
    ]
    const wrapper = mountUpload()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    const start = wrapper.findAll('button').find((button) => button.text() === '开始上报')
    await start.trigger('click')
    await flushPromises()

    expect(messageMock.warning).toHaveBeenCalledWith(
      '批次 #dup 已存在，请勾选“覆盖同号批次”后再上报',
    )
    expect(apiMock.createBatch).not.toHaveBeenCalled()
  })
})
