// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const { storeMock } = vi.hoisted(() => ({
  storeMock: {
    selectedComparison: { id: 1 },
    pageSize: 10,
    page: 1,
    sceneSearch: '',
    sceneSort: 'name',
    settings: { fail_threshold: 2, warn_threshold: 0.3 },
    loading: false,
    sceneError: '',
    scenes: [],
    orientedScenes: [],
    sceneTotal: 0,
    selectedSceneItemId: null,
    loadScenes: vi.fn(),
    toggleSceneSort: vi.fn(),
    selectScene: vi.fn(),
  },
}))

vi.mock('../store', () => ({ useStore: () => storeMock }))
vi.mock('../api', () => ({ thumbUrl: (url) => url }))

import SceneList from './SceneList.vue'

const InputStub = defineComponent({
  emits: ['input', 'clear'],
  template: '<input @input="$emit(\'input\', $event.target.value)">',
})
const SlotStub = defineComponent({ template: '<div><slot/></div>' })

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('SceneList', () => {
  it('输入搜索后立即卸载会清除防抖定时器，不在离页后重新请求', async () => {
    const wrapper = mount(SceneList, {
      global: {
        stubs: {
          'a-input': InputStub,
          'a-button': SlotStub,
          'a-spin': SlotStub,
          'a-empty': SlotStub,
          Pager: SlotStub,
        },
      },
    })

    await wrapper.get('input').setValue('late-search')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(300)

    expect(storeMock.loadScenes).not.toHaveBeenCalled()
    expect(storeMock.sceneSearch).toBe('')
  })
})
