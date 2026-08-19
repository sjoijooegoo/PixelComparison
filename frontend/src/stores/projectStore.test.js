import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  meta: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
  batches: vi.fn(),
  sceneGrid: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))

import { useProjectStore } from './projectStore'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.meta.mockResolvedValue({
    branch_tags: ['engine-ue5'],
    scene_ids: ['SceneA'],
    scene_data_flags: { 'engine-ue5': { SceneA: { has_screenshots: true } } },
  })
  apiMock.settings.mockResolvedValue({ default_shading_quality: 4 })
})

describe('project initialization', () => {
  it('并发初始化只加载项目元信息和设置，不加载任何页面数据', async () => {
    const store = useProjectStore()

    await Promise.all([store.init(), store.init()])

    expect(apiMock.meta).toHaveBeenCalledTimes(1)
    expect(apiMock.settings).toHaveBeenCalledTimes(1)
    expect(apiMock.batches).not.toHaveBeenCalled()
    expect(apiMock.sceneGrid).not.toHaveBeenCalled()
    expect(store.meta.branch_tags).toEqual(['main', 'engine-ue5'])
    expect(store.meta.scene_data_flags['engine-ue5'].SceneA.has_screenshots).toBe(true)
    expect(store.settings.default_shading_quality).toBe(4)
  })
})
