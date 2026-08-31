// @vitest-environment happy-dom

import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GpmMapLibraryPane from './GpmMapLibraryPane.vue'

const ButtonStub = defineComponent({
  emits: ['click'],
  template: '<button @click="$emit(\'click\')"><slot /></button>',
})
const InputStub = defineComponent({ template: '<input />' })

describe('GpmMapLibraryPane', () => {
  it('保留地图规范名并从对应行发出删除事件', async () => {
    const map = {
      id: 0,
      map_name: 'Forest_WP',
      revision: 2,
      image: null,
      bindings: [],
    }
    const wrapper = mount(GpmMapLibraryPane, {
      props: { maps: [map] },
      global: {
        stubs: {
          'a-button': ButtonStub,
          'a-input': InputStub,
        },
      },
    })

    expect(wrapper.get('strong').text()).toBe('Forest_WP')
    const deleteButton = wrapper.findAll('button')
      .find((button) => button.text() === '删除')
    await deleteButton.trigger('click')

    expect(wrapper.emitted('delete')).toEqual([[map]])
  })
})
