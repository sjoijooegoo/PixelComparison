// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerMock = vi.hoisted(() => ({ push: vi.fn() }))
const storeMock = vi.hoisted(() => ({
  batchTotal: 0,
  batches: [],
  batchError: '',
  batchLoading: false,
  batchPage: 1,
  batchPageSize: 10,
  loadBatches: vi.fn(),
  deleteBatch: vi.fn(),
}))
const tableSizerMock = vi.hoisted(() => ({
  observe: vi.fn(),
  disconnect: vi.fn(),
  recalc: vi.fn(),
}))

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRouter: () => routerMock,
}))
vi.mock('../stores/batchCatalogStore', () => ({ useBatchCatalogStore: () => storeMock }))
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
        'a-popconfirm': PassthroughStub,
        Pager: true,
        BatchPreview: true,
      },
    },
  })
}

function button(row, label) {
  return row.findAll('button').find((item) => item.text() === label)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BatchTable 数据能力操作', () => {
  it('展示目录操作，并按截图和烘培能力分别禁用', () => {
    const wrapper = mountTable([
      { id: 'empty', has_screenshots: false, has_map_build_data: false },
      { id: 'map', has_screenshots: false, has_map_build_data: true },
      { id: 'shots', has_screenshots: true, has_map_build_data: false },
    ])
    const [emptyRow, mapRow, shotsRow] = wrapper.findAll('.batch-row')

    expect(button(emptyRow, '预览').element.disabled).toBe(true)
    expect(button(mapRow, '预览').element.disabled).toBe(true)
    expect(button(shotsRow, '预览').element.disabled).toBe(false)
    expect(button(emptyRow, '查看烘培数据').element.disabled).toBe(true)
    expect(button(mapRow, '查看烘培数据').element.disabled).toBe(false)
    expect(button(shotsRow, '查看烘培数据').element.disabled).toBe(true)
    expect(button(emptyRow, '预览').attributes('title')).toBe('该批次没有截图数据')
    expect(button(shotsRow, '预览').attributes('title')).toBeUndefined()
    expect(button(emptyRow, '查看烘培数据').attributes('title')).toBe('该批次没有烘培数据')
    expect(button(mapRow, '查看烘培数据').attributes('title')).toBeUndefined()

    expect(wrapper.text()).not.toContain('设为基线')
    expect(wrapper.text()).not.toContain('设为对比')
    expect(wrapper.text()).not.toContain('列表图')
    expect(wrapper.text()).not.toContain('截图对比')
    expect(wrapper.text()).not.toContain('批次列表')
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

    await button(emptyRow, '查看烘培数据').trigger('click')
    expect(routerMock.push).not.toHaveBeenCalled()
    await button(mapRow, '查看烘培数据').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/map-build/SceneA',
      query: { branch_tag: 'engine-ue5', batch: 'map' },
    })
    wrapper.unmount()
  })
})
