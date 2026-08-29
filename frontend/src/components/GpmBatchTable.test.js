// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routeMock = vi.hoisted(() => ({ query: {} }))
const routerMock = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
const storeMock = vi.hoisted(() => ({
  batches: [],
  batchTotal: 0,
  batchPage: 1,
  batchPageSize: 10,
  error: '',
  loading: false,
  filters: {},
  loadBatches: vi.fn(),
  deleteBatch: vi.fn(),
}))
const tableSizerMock = vi.hoisted(() => ({
  observe: vi.fn(),
  disconnect: vi.fn(),
  recalc: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))
vi.mock('../stores/gpmBatchStore', () => ({ useGpmBatchStore: () => storeMock }))
vi.mock('./batchTableSizer', () => ({ createBatchTableSizer: () => tableSizerMock }))
vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn() },
}))

import GpmBatchTable from './GpmBatchTable.vue'

const TableStub = defineComponent({
  props: { data: { type: Array, default: () => [] } },
  template: `
    <div>
      <div v-for="record in data" :key="record.id" class="batch-row">
        <div class="batch-cell"><slot name="batch" :record="record" /></div>
        <div class="ops-cell"><slot name="ops" :record="record" /></div>
      </div>
    </div>
  `,
})
const PassthroughStub = defineComponent({ template: '<div><slot/></div>' })
const ButtonStub = defineComponent({ template: '<button><slot/><slot name="icon"/></button>' })

function mountTable(records) {
  storeMock.batches = records
  storeMock.batchTotal = records.length
  return mount(GpmBatchTable, {
    global: {
      stubs: {
        'a-table': TableStub,
        'a-button': ButtonStub,
        'a-popconfirm': PassthroughStub,
        'a-tag': PassthroughStub,
        Pager: true,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('GpmBatchTable 流水线入口', () => {
  it('把流水线链接放在批次 ID 上并移除操作列按钮', () => {
    const wrapper = mountTable([
      {
        id: 1,
        batch_id: 'gpm-1',
        batch_url: 'https://example.test/pipeline/gpm-1',
        map_names: ['SceneA'],
      },
      { id: 2, batch_id: 'gpm-2', batch_url: '', map_names: ['SceneB'] },
    ])
    const [linkedRow, plainRow] = wrapper.findAll('.batch-row')
    const link = linkedRow.get('.batch-link')

    expect(link.text()).toBe('#gpm-1')
    expect(link.attributes()).toMatchObject({
      href: 'https://example.test/pipeline/gpm-1',
      target: '_blank',
      rel: 'noopener noreferrer',
      title: '查看流水线',
    })
    expect(plainRow.find('a').exists()).toBe(false)
    expect(plainRow.get('.batch-id').text()).toBe('#gpm-2')
    expect(wrapper.findAll('.ops-cell').every((cell) => !cell.text().includes('流水线'))).toBe(true)
  })
})
