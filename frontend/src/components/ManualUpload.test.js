// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  batches: vi.fn(),
  createBatch: vi.fn(),
  uploadMapBuildData: vi.fn(),
  uploadScreenshot: vi.fn(),
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
    )
    expect(apiMock.uploadScreenshot).toHaveBeenCalledTimes(1)
    expect(messageMock.warning).toHaveBeenCalledWith('批次 #77 上报完成，但烘培数据失败')
    expect(wrapper.emitted('done')).toHaveLength(1)
    expect(wrapper.emitted('update:visible')).toContainEqual([false])
  })
})
