// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import { useProjectStore } from '../stores/projectStore'
import { useScreenshotComparisonStore } from '../stores/screenshotComparisonStore'
import ScreenshotFilters from './ScreenshotFilters.vue'

const SlotStub = defineComponent({ template: '<div><slot/></div>' })
const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<div><slot/></div>',
})

let router
let wrapper

async function flushNavigation() {
  await Promise.resolve()
  await nextTick()
  await Promise.resolve()
}

function mountFilters() {
  wrapper = mount(ScreenshotFilters, {
    global: {
      plugins: [router],
      stubs: {
        'a-select': SelectStub,
        'a-option': SlotStub,
        'a-radio-group': SlotStub,
        'a-radio': SlotStub,
        'a-range-picker': SlotStub,
        'a-date-picker': SlotStub,
        'a-button': SlotStub,
        'a-tag': SlotStub,
      },
    },
  })
  return wrapper
}

beforeEach(async () => {
  setActivePinia(createPinia())
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/screenshot/:sceneId?', component: SlotStub }],
  })
  await router.push('/screenshot/SceneA?branch_tag=main')
  await router.isReady()

  const project = useProjectStore()
  project.meta.branch_tags = ['main']
  project.meta.scene_ids = ['SceneA', 'SceneB']
  project.settings.default_shading_quality = 5
  project.settings.default_date_range_days = 7

  const store = useScreenshotComparisonStore()
  store.filters = {
    branch_tag: 'main',
    scene_id: 'SceneA',
    shading_quality: 3,
    dateMode: 'range',
    created_from: '2026-08-01',
    created_to: '2026-08-07',
    created_dates: [],
  }
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
})

describe('ScreenshotFilters route state', () => {
  it('切换场景时把当前画质和日期一起写入新路由', async () => {
    const push = vi.spyOn(router, 'push')
    mountFilters()
    wrapper.findAllComponents(SelectStub)[1].vm.$emit('change', 'SceneB')
    await flushNavigation()

    expect(push).toHaveBeenCalledWith({
      path: '/screenshot/SceneB',
      query: {
        branch_tag: 'main',
        quality: '3',
        date_mode: 'range',
        from: '2026-08-01',
        to: '2026-08-07',
      },
    })
  })

  it('修改画质使用 replace 更新路由而不是直接请求数据', async () => {
    const store = useScreenshotComparisonStore()
    const replace = vi.spyOn(router, 'replace')
    store.applyFilters = vi.fn()
    mountFilters()
    wrapper.findAllComponents(SelectStub)[2].vm.$emit('change', 4)
    await flushNavigation()

    expect(replace).toHaveBeenCalledWith(expect.objectContaining({
      path: '/screenshot/SceneA',
      query: expect.objectContaining({ quality: '4' }),
    }))
    expect(store.applyFilters).not.toHaveBeenCalled()
    expect(store.filters.shading_quality).toBe(3)
  })
})
