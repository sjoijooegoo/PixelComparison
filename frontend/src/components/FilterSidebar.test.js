// @vitest-environment happy-dom
import { defineComponent, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'
import FilterSidebar from './FilterSidebar.vue'

const SlotStub = defineComponent({ template: '<div><slot/></div>' })
const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<div><slot/></div>',
})

function mountSidebar() {
  return mount(FilterSidebar, {
    global: {
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
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('FilterSidebar scene data availability', () => {
  it('批次目录只将当前分支完全没有批次的场景置灰，并保持选项可选', async () => {
    const project = useProjectStore()
    const store = useBatchCatalogStore()
    project.meta.scene_ids = ['ShotScene', 'BuildOnlyScene', 'CatalogOnlyScene']
    project.meta.scene_data_flags = {
      main: {
        ShotScene: { has_screenshots: true, has_map_build_data: false },
        BuildOnlyScene: { has_screenshots: false, has_map_build_data: true },
      },
      'engine-ue5': {
        ShotScene: { has_screenshots: false, has_map_build_data: true },
        BuildOnlyScene: { has_screenshots: true, has_map_build_data: false },
      },
    }

    const wrapper = mountSidebar()
    const names = wrapper.findAll('.scene-option-name')
    expect(names.map((name) => name.classes('is-data-empty'))).toEqual([false, false, true])
    expect(names[2].attributes('title')).toBe('当前分支没有批次数据')

    store.filters.branch_tag = 'engine-ue5'
    await nextTick()
    expect(wrapper.findAll('.scene-option-name').map(
      (name) => name.classes('is-data-empty'),
    )).toEqual([false, false, true])
  })
})
