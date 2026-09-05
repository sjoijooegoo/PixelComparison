// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routeMock = vi.hoisted(() => ({ query: {} }))
const routerMock = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
const apiMock = vi.hoisted(() => ({ exportGpmOfflinePackage: vi.fn() }))
const messageMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('../api', () => ({ api: apiMock }))
const storeMock = vi.hoisted(() => ({
  batches: [],
  batchTotal: 0,
  batchPage: 1,
  batchPageSize: 10,
  error: '',
  loading: false,
  focusBatchId: '',
  locationMessage: '',
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
  Message: messageMock,
}))

import GpmBatchTable from './GpmBatchTable.vue'

const TableStub = defineComponent({
  props: { data: { type: Array, default: () => [] }, rowClass: Function },
  template: `
    <div>
      <div v-for="record in data" :key="record.id" class="batch-row" :class="rowClass?.(record)">
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
  storeMock.focusBatchId = ''
  storeMock.locationMessage = ''
  storeMock.filters = { branchTag: 'main' }
})
afterEach(() => vi.restoreAllMocks())

describe('GpmBatchTable 流水线入口', () => {
  it('仅高亮来源分支的目标批次，不显示文字标记', () => {
    storeMock.focusBatchId = 'source'
    const wrapper = mountTable([
      { id: 1, batch_id: 'source', branch_tag: 'main' },
      { id: 2, batch_id: 'other', branch_tag: 'main' },
    ])
    expect(wrapper.findAll('.focused-batch')).toHaveLength(1)
    expect(wrapper.get('.focused-batch').text()).toContain('#source')
    expect(wrapper.get('.focused-batch').text()).not.toContain('来源批次')
    wrapper.unmount()
  })
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

describe('GpmBatchTable 离线导出', () => {
  const record = { id: 1, batch_id: '67526', branch_tag: 'engine-ue5', map_names: ['SceneA'] }

  it('下载当前行批次，等待期间防止重复请求，并提示放入 data', async () => {
    let resolve
    apiMock.exportGpmOfflinePackage.mockReturnValue(new Promise((done) => { resolve = done }))
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:offline')
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    let downloaded
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      downloaded = { href: this.href, filename: this.download }
    })
    const wrapper = mountTable([record])
    const button = wrapper.get('.export-button')
    await button.trigger('click')
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(apiMock.exportGpmOfflinePackage).toHaveBeenCalledExactlyOnceWith('67526', 'engine-ue5')
    const blob = new Blob(['ssheat'])
    const filename = 'SceneScope-heatmap-engine-ue5-67526.ssheat'
    resolve({ blob, filename })
    await flushPromises()
    expect(create).toHaveBeenCalledWith(blob)
    expect(downloaded).toEqual({ href: 'blob:offline', filename })
    expect(revoke).toHaveBeenCalledWith('blob:offline')
    expect(messageMock.success).toHaveBeenCalledWith(expect.stringContaining('data 目录后刷新'))
    expect(button.attributes('disabled')).toBeUndefined()
    expect(storeMock.deleteBatch).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('失败显示原因并恢复导出按钮，允许重试', async () => {
    apiMock.exportGpmOfflinePackage.mockRejectedValue(new Error('批次已删除'))
    const wrapper = mountTable([record])
    const button = wrapper.get('.export-button')
    await button.trigger('click')
    await flushPromises()
    expect(messageMock.error).toHaveBeenCalledWith('批次已删除')
    expect(messageMock.success).not.toHaveBeenCalled()
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    await flushPromises()
    expect(apiMock.exportGpmOfflinePackage).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
