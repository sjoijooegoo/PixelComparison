// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { apiMock, messageMock } = vi.hoisted(() => ({
  apiMock: { batchScreenshots: vi.fn() },
  messageMock: { error: vi.fn() },
}))

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    api: apiMock,
    isRequestCancelled: (error) => error?.code === 'ABORTED',
  }
})
vi.mock('../store', () => ({ p4Label: (value) => `P4 ${value}` }))
vi.mock('@arco-design/web-vue', () => ({ Message: messageMock }))

import BatchPreview from './BatchPreview.vue'

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

const SlotStub = defineComponent({ template: '<div><slot name="title"/><slot/></div>' })
const PreviewGroupStub = defineComponent({
  props: ['srcList', 'visible', 'current'],
  emits: ['update:visible', 'update:current'],
  template: '<div class="preview-group"><slot/></div>',
})

function batch(id) {
  return { id, scene_id: 'SceneA', platform: 'Windows', p4_version: 1, shading_quality_label: '电影' }
}

function mountPreview(props = { visible: false, batch: batch('A') }) {
  return mount(BatchPreview, {
    props,
    global: {
      stubs: {
        'a-modal': SlotStub,
        'a-spin': SlotStub,
        'a-empty': SlotStub,
        'a-image-preview-group': PreviewGroupStub,
      },
    },
  })
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.useRealTimers())

describe('BatchPreview', () => {
  it('关闭并打开另一批次时取消旧清单请求，晚到响应不会覆盖新批次', async () => {
    const requestA = deferred()
    const requestB = deferred()
    apiMock.batchScreenshots
      .mockImplementationOnce(() => requestA.promise)
      .mockImplementationOnce(() => requestB.promise)
    const wrapper = mountPreview()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const signalA = apiMock.batchScreenshots.mock.calls[0][1].signal

    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ batch: batch('B'), visible: true })
    await flushPromises()
    expect(signalA.aborted).toBe(true)

    requestB.resolve({ items: [{ scene_name: 'new-shot', url: '/images/b.png?v=2' }] })
    await flushPromises()
    expect(wrapper.text()).toContain('new-shot')

    requestA.resolve({ items: [{ scene_name: 'stale-shot', url: '/images/a.png?v=1' }] })
    await flushPromises()
    expect(wrapper.text()).not.toContain('stale-shot')
    expect(messageMock.error).not.toHaveBeenCalled()
  })

  it('卡片只挂载严格缩略图，点击后才把原图交给灯箱', async () => {
    apiMock.batchScreenshots.mockResolvedValue({
      items: [{ scene_name: 'shot', url: '/images/batches/A/shot.png?v=1' }],
    })
    const wrapper = mountPreview()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    const image = wrapper.get('img')
    expect(image.attributes('src')).toBe('/thumb/batches/A/shot.png?v=1&strict=true')
    const group = wrapper.getComponent(PreviewGroupStub)
    expect(group.props('srcList')).toEqual(['/images/batches/A/shot.png?v=1'])
    expect(group.props('visible')).toBe(false)

    await image.trigger('click')
    expect(group.emitted('update:visible')).toBeUndefined()
    await nextTick()
    expect(wrapper.getComponent(PreviewGroupStub).props('visible')).toBe(true)
  })

  it('缩略图多次未就绪后提供手动重试，卸载会取消清单请求', async () => {
    vi.useFakeTimers()
    apiMock.batchScreenshots.mockResolvedValue({
      items: [{ scene_name: 'slow-shot', url: '/images/slow.png?v=1' }],
    })
    const wrapper = mountPreview()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    for (let index = 0; index < 16; index += 1) {
      await wrapper.get('img').trigger('error')
      await vi.runOnlyPendingTimersAsync()
      await nextTick()
    }
    expect(wrapper.text()).toContain('缩略图生成较慢，重试')

    await wrapper.get('.thumb-retry').trigger('click')
    expect(wrapper.text()).not.toContain('缩略图生成较慢，重试')
    expect(wrapper.get('img').attributes('src')).toContain('&retry=')

    const pending = deferred()
    apiMock.batchScreenshots.mockReturnValueOnce(pending.promise)
    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ batch: batch('C'), visible: true })
    await flushPromises()
    const signal = apiMock.batchScreenshots.mock.calls.at(-1)[1].signal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
  })
})
