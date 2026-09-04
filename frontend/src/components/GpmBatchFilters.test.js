// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import { useGpmBatchStore } from '../stores/gpmBatchStore'
import GpmBatchFilters from './GpmBatchFilters.vue'

const SlotStub = defineComponent({ template: '<span><slot/></span>' })
const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<button type="button"><slot/></button>',
})
const RangeStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<button type="button"></button>',
})
const ButtonStub = defineComponent({ template: '<button type="button"><slot/></button>' })

let router

beforeEach(async () => {
  setActivePinia(createPinia())
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/batch-management/gpm', component: SlotStub }],
  })
  await router.push('/batch-management/gpm?branch_tag=main&platform=Android&quality=4')
  await router.isReady()

  const store = useGpmBatchStore()
  store.meta = {
    branch_tags: ['main'],
    platforms: ['IOS', 'Android', 'Windows'],
    maps: ['Forest_WP'],
    shading_qualities: [{ value: 4, label: '极致' }],
  }
  Object.assign(store.filters, {
    branchTag: 'main', platform: 'Android', mapName: 'Forest_WP', shadingQuality: 4,
    capturedFrom: '2026-08-06', capturedTo: '2026-09-04',
  })
})

describe('GpmBatchFilters', () => {
  it('不使用原生 label 包裹下拉框，避免已选值触发二次点击并关闭菜单', () => {
    const wrapper = mount(GpmBatchFilters, {
      global: {
        plugins: [router],
        stubs: {
          'a-select': SelectStub,
          'a-option': SlotStub,
          'a-range-picker': RangeStub,
          'a-button': ButtonStub,
        },
      },
    })

    const fields = wrapper.findAll('.filter-field')
    expect(fields).toHaveLength(5)
    expect(fields.every((field) => field.element.tagName === 'DIV')).toBe(true)
    expect(wrapper.find('label.filter-field').exists()).toBe(false)
    expect(wrapper.get('.select-platform').attributes('aria-label')).toBe('平台')
    expect(wrapper.get('.select-quality').attributes('aria-label')).toBe('画质')
    expect(wrapper.get('.select-range').attributes('aria-label')).toBe('采集时间')
  })
})
