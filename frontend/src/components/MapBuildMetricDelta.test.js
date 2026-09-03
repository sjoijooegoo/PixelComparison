// @vitest-environment happy-dom
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MapBuildMetricDelta from './MapBuildMetricDelta.vue'
import { HEAT_COLORS } from '../gpmHeatmap/colors'

const TooltipStub = defineComponent({
  template: '<div><slot/><div class="tooltip-content"><slot name="content"/></div></div>',
})

describe('MapBuildMetricDelta', () => {
  it('提示面板只展示当前值和对比值', () => {
    const wrapper = mount(MapBuildMetricDelta, {
      props: {
        currentValue: 2 * 1024 * 1024,
        previousValue: 1024 * 1024,
        enabled: true,
        baselineAvailable: true,
      },
      global: { stubs: { 'a-tooltip': TooltipStub } },
    })

    const tooltip = wrapper.get('.tooltip-content')
    expect(tooltip.text()).toContain('当前2.00 MiB')
    expect(tooltip.text()).toContain('对比批次1.00 MiB')
    expect(tooltip.text()).not.toContain('P4')
    expect(tooltip.text()).not.toContain('变化')
  })

  it('按变化比例复用热力图的五段色阶', async () => {
    const wrapper = mount(MapBuildMetricDelta, {
      props: {
        currentValue: 90,
        previousValue: 100,
        enabled: true,
        baselineAvailable: true,
        percentRange: [-20, 30],
      },
      global: { stubs: { 'a-tooltip': TooltipStub } },
    })

    expect(wrapper.get('.metric-delta').element.style.color).toBe(HEAT_COLORS[0])

    await wrapper.setProps({ currentValue: 97 })
    expect(wrapper.get('.metric-delta').element.style.color).toBe(HEAT_COLORS[1])

    await wrapper.setProps({ currentValue: 103 })
    expect(wrapper.get('.metric-delta').element.style.color).toBe(HEAT_COLORS[2])

    await wrapper.setProps({ currentValue: 115 })
    expect(wrapper.get('.metric-delta').element.style.color).toBe(HEAT_COLORS[3])

    await wrapper.setProps({ currentValue: 130 })
    expect(wrapper.get('.metric-delta').element.style.color).toBe(HEAT_COLORS[4])

    await wrapper.setProps({ currentValue: 100 })
    expect(wrapper.get('.metric-delta').element.style.color).toBe('')
  })
})
