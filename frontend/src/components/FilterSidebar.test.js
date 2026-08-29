// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'
import FilterSidebar from './FilterSidebar.vue'

const SlotStub = defineComponent({ template: '<div><slot/></div>' })
const ButtonStub = defineComponent({
  emits: ['click'],
  template: '<button @click="$emit(\'click\')"><slot/></button>',
})
const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<div><slot/></div>',
})

let router

function mountSidebar() {
  return mount(FilterSidebar, {
    global: {
      plugins: [router],
      stubs: {
        'a-select': SelectStub,
        'a-option': SlotStub,
        'a-radio-group': SlotStub,
        'a-radio': SlotStub,
        'a-range-picker': SlotStub,
        'a-date-picker': SlotStub,
        'a-button': ButtonStub,
        'a-tag': SlotStub,
      },
    },
  })
}

beforeEach(async () => {
  setActivePinia(createPinia())
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/batch-management/capture', component: SlotStub }],
  })
  await router.push('/batch-management/capture')
  await router.isReady()
})

describe('FilterSidebar scene data availability', () => {
  it('批次管理不展示画质筛选', () => {
    const wrapper = mountSidebar()

    expect(wrapper.text()).not.toContain('画质')
    expect(wrapper.findAllComponents(SelectStub)).toHaveLength(2)
  })

  it('批次目录按当前筛选聚合结果置灰，并保持选项可选', async () => {
    const project = useProjectStore()
    const store = useBatchCatalogStore()
    project.meta.scene_ids = ['ShotScene', 'BuildOnlyScene', 'CatalogOnlyScene']
    store.availableSceneIds = ['ShotScene', 'BuildOnlyScene']

    const wrapper = mountSidebar()
    const names = wrapper.findAll('.scene-option-name')
    expect(names.map((name) => name.classes('is-data-empty'))).toEqual([false, false, true])
    expect(names[2].attributes('title')).toBe('当前筛选范围内没有批次数据')

    store.availableSceneIds = ['BuildOnlyScene']
    await nextTick()
    expect(wrapper.findAll('.scene-option-name').map(
      (name) => name.classes('is-data-empty'),
    )).toEqual([true, false, true])
  })

  it('切换场景时把当前筛选写入路由且不直接修改 Store', async () => {
    const store = useBatchCatalogStore()
    const project = useProjectStore()
    project.meta.scene_ids = ['SceneA', 'SceneB']
    store.filters = {
      branch_tag: 'main',
      scene_id: 'SceneA',
      dateMode: 'range',
      rangeMode: 'fixed',
      created_from: '2026-08-14',
      created_to: '2026-08-20',
      created_dates: [],
    }
    const push = vi.spyOn(router, 'push')
    const wrapper = mountSidebar()

    wrapper.findAllComponents(SelectStub)[1].vm.$emit('change', 'SceneB')
    await nextTick()

    expect(push).toHaveBeenCalledWith({
      path: '/batch-management/capture',
      query: {
        branch_tag: 'main',
        scene_id: 'SceneB',
        date_mode: 'range',
        range_mode: 'fixed',
        from: '2026-08-14',
        to: '2026-08-20',
      },
    })
    expect(store.filters.scene_id).toBe('SceneA')
  })

  it('清空筛选写入 main 和全部场景', async () => {
    const store = useBatchCatalogStore()
    store.filters.branch_tag = 'engine-ue5'
    store.filters.scene_id = 'SceneA'
    const replace = vi.spyOn(router, 'replace')
    const wrapper = mountSidebar()

    wrapper.findAllComponents(ButtonStub).find(
      (button) => button.text() === '清空',
    ).vm.$emit('click')
    await nextTick()

    expect(replace).toHaveBeenCalledWith(expect.objectContaining({
      path: '/batch-management/capture',
      query: expect.objectContaining({
        branch_tag: 'main',
      }),
    }))
    expect(replace.mock.calls[0][0].query).not.toHaveProperty('scene_id')
    expect(replace.mock.calls[0][0].query).not.toHaveProperty('quality')
  })
})
