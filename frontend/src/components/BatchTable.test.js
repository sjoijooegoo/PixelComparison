// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerMock = vi.hoisted(() => ({ push: vi.fn() }))
const storeMock = vi.hoisted(() => ({
  batchView: 'list',
  batchTotal: 0,
  batches: [],
  batchError: '',
  batchLoading: false,
  batchPage: 1,
  batchPageSize: 10,
  baselineBatch: null,
  currentBatch: null,
  canCompare: false,
  running: false,
  progress: { done: 0, total: 0 },
  loadBatches: vi.fn(),
  loadGrid: vi.fn(),
  setRole: vi.fn(),
  clearRole: vi.fn(),
  deleteBatch: vi.fn(),
}))
const tableSizerMock = vi.hoisted(() => ({
  observe: vi.fn(),
  disconnect: vi.fn(),
  recalc: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => routerMock }))
vi.mock('../store', () => ({ useStore: () => storeMock }))
vi.mock('./batchTableSizer', () => ({ createBatchTableSizer: () => tableSizerMock }))
vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

import BatchTable from './BatchTable.vue'

const ButtonStub = defineComponent({
  inheritAttrs: false,
  props: { disabled: Boolean, title: String },
  emits: ['click'],
  template: '<button :disabled="disabled" :title="title" :style="$attrs.style" @click="$emit(\'click\')"><slot/><slot name="icon"/></button>',
})
const TableStub = defineComponent({
  props: { data: { type: Array, default: () => [] } },
  template: '<div><div v-for="record in data" :key="record.id" class="batch-row" :data-id="record.id"><slot name="ops" :record="record"/></div></div>',
})
const PassthroughStub = defineComponent({ template: '<div><slot/></div>' })

function mountTable(records) {
  storeMock.batches = records
  storeMock.batchTotal = records.length
  return mount(BatchTable, {
    global: {
      stubs: {
        'a-button': ButtonStub,
        'a-table': TableStub,
        'a-radio-group': PassthroughStub,
        'a-radio': PassthroughStub,
        'a-popconfirm': PassthroughStub,
        Pager: true,
        BatchPreview: true,
        BatchGrid: true,
      },
    },
  })
}

function button(row, label) {
  return row.findAll('button').find((item) => item.text() === label)
}

beforeEach(() => {
  vi.clearAllMocks()
  storeMock.batchView = 'list'
  storeMock.baselineBatch = null
  storeMock.currentBatch = null
})

describe('BatchTable 数据能力操作', () => {
  it('始终展示四个数据入口，并按截图和烘培能力分别禁用', () => {
    const wrapper = mountTable([
      { id: 'empty', has_screenshots: false, has_map_build_data: false },
      { id: 'map', has_screenshots: false, has_map_build_data: true },
      { id: 'shots', has_screenshots: true, has_map_build_data: false },
    ])
    const [emptyRow, mapRow, shotsRow] = wrapper.findAll('.batch-row')

    for (const label of ['预览', '设为基线', '设为对比']) {
      expect(button(emptyRow, label).element.disabled).toBe(true)
      expect(button(mapRow, label).element.disabled).toBe(true)
      expect(button(shotsRow, label).element.disabled).toBe(false)
    }
    expect(button(emptyRow, '查看烘培数据').element.disabled).toBe(true)
    expect(button(mapRow, '查看烘培数据').element.disabled).toBe(false)
    expect(button(shotsRow, '查看烘培数据').element.disabled).toBe(true)

    // 禁用的角色按钮不得残留蓝/橙强调色，否则视觉上仍会像可点击。
    expect(button(emptyRow, '设为基线').attributes('style') || '').not.toContain('color')
    expect(button(emptyRow, '设为对比').attributes('style') || '').not.toContain('color')
    wrapper.unmount()
  })

  it('禁用入口不执行操作，可用入口仍正常选择和跳转', async () => {
    const records = [
      { id: 'empty', scene_id: 'SceneA', branch_tag: 'engine-ue5', has_screenshots: false, has_map_build_data: false },
      { id: 'map', scene_id: 'SceneA', branch_tag: 'engine-ue5', has_screenshots: false, has_map_build_data: true },
      { id: 'shots', scene_id: 'SceneA', branch_tag: 'engine-ue5', has_screenshots: true, has_map_build_data: false },
    ]
    const wrapper = mountTable(records)
    const [emptyRow, mapRow, shotsRow] = wrapper.findAll('.batch-row')

    await button(emptyRow, '设为基线').trigger('click')
    await button(emptyRow, '设为对比').trigger('click')
    await button(emptyRow, '查看烘培数据').trigger('click')
    expect(storeMock.setRole).not.toHaveBeenCalled()
    expect(routerMock.push).not.toHaveBeenCalled()

    await button(shotsRow, '设为基线').trigger('click')
    expect(storeMock.setRole).toHaveBeenCalledWith(records[2], 'baseline')

    await button(mapRow, '查看烘培数据').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/map-build/SceneA',
      query: { branch_tag: 'engine-ue5', batch: 'map' },
    })
    wrapper.unmount()
  })
})
