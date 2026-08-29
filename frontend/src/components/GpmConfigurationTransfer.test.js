// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  exportGpmConfiguration: vi.fn(),
  inspectGpmConfiguration: vi.fn(),
  applyGpmConfigurationImport: vi.fn(),
}))
const messageMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
const storeMock = vi.hoisted(() => ({ load: vi.fn() }))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../stores/gpmScaleConfigStore', () => ({ useGpmScaleConfigStore: () => storeMock }))
vi.mock('@arco-design/web-vue', async (importOriginal) => ({
  ...(await importOriginal()),
  Message: messageMock,
}))

import GpmConfigurationTransfer from './GpmConfigurationTransfer.vue'

const ButtonStub = {
  props: ['disabled', 'loading'],
  emits: ['click'],
  template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
}
const ModalStub = {
  props: ['visible'],
  emits: ['cancel'],
  template: '<div v-if="visible" class="modal-stub"><slot name="title"/><slot/></div>',
}
const TooltipStub = { template: '<span><slot /></span>' }

function mountTransfer() {
  return mount(GpmConfigurationTransfer, {
    global: {
      stubs: {
        'a-button': ButtonStub,
        'a-modal': ModalStub,
        'a-spin': { template: '<span class="spin-stub" />' },
        'a-tooltip': TooltipStub,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  storeMock.load.mockResolvedValue()
})

describe('GpmConfigurationTransfer', () => {
  it('检查配置包后展示变更，并只在检查通过后应用', async () => {
    apiMock.inspectGpmConfiguration.mockResolvedValue({
      valid: true,
      import_id: 'checked-import',
      issues: [],
      summary: {
        maps: { included: true, total: 2, new: 1, updated: 1, unchanged: 0 },
        metric_scales: { included: false, total: 0, new: 0, updated: 0, unchanged: 0 },
        scale_sets: { included: false, total: 0, new: 0, updated: 0, unchanged: 0 },
        map_bindings: { included: false, total: 0, new: 0, updated: 0, unchanged: 0 },
        images: { included: true, total: 2, added: 1, replaced: 0, removed: 0, unchanged: 1 },
      },
      changes: [{
        kind: 'maps', kind_label: '地图', identity: 'Village', name: 'Village',
        action: 'updated', details: ['坐标范围'],
      }],
    })
    apiMock.applyGpmConfigurationImport.mockResolvedValue({ applied: true })
    const wrapper = mountTransfer()
    const input = wrapper.get('input[type="file"]')
    const file = new File(['zip'], 'edited-config.zip', { type: 'application/zip' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })

    await input.trigger('change')
    await flushPromises()

    expect(apiMock.inspectGpmConfiguration).toHaveBeenCalledWith(file)
    expect(wrapper.text()).toContain('配置包检查通过')
    expect(wrapper.text()).toContain('地图 · Village')
    expect(wrapper.text()).toContain('坐标范围')

    const applyButton = wrapper.findAll('button').find((button) => button.text().includes('应用配置'))
    await applyButton.trigger('click')
    await flushPromises()

    expect(apiMock.applyGpmConfigurationImport).toHaveBeenCalledWith('checked-import')
    expect(storeMock.load).toHaveBeenCalledTimes(1)
  })

  it('校验失败时展示问题且禁用应用', async () => {
    apiMock.inspectGpmConfiguration.mockResolvedValue({
      valid: false,
      import_id: null,
      summary: null,
      changes: [],
      issues: [{ code: 'BAD_REFERENCE', scope: 'scale_sets/0', message: '引用不存在' }],
    })
    const wrapper = mountTransfer()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['zip'], 'broken.zip')], configurable: true,
    })

    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('配置包不能应用')
    expect(wrapper.text()).toContain('引用不存在')
    const applyButton = wrapper.findAll('button').find((button) => button.text().includes('应用配置'))
    expect(applyButton.attributes('disabled')).toBeDefined()
  })

  it('从图标打开导出范围选择，并按地图资源范围下载', async () => {
    const archive = new Blob(['zip'], { type: 'application/zip' })
    apiMock.exportGpmConfiguration.mockResolvedValue({
      blob: archive, filename: 'gpm-heatmap-config-maps.zip',
    })
    const createObjectURL = vi.fn().mockReturnValue('blob:config')
    const revokeObjectURL = vi.fn()
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mountTransfer()

    await wrapper.get('button[aria-label="导出热力图配置"]').trigger('click')
    const mapsButton = wrapper.findAll('.export-options button')
      .find((button) => button.text().includes('地图与图片'))
    await mapsButton.trigger('click')
    await flushPromises()

    expect(apiMock.exportGpmConfiguration).toHaveBeenCalledWith('maps')
    expect(messageMock.success).toHaveBeenCalledWith('热力图配置已导出')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:config')
  })
})
