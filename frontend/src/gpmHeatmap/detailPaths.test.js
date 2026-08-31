import { describe, expect, it } from 'vitest'

import { detailNodeIdentity, detailNodePath } from './detailPaths'

describe('GPM detail semantic paths', () => {
  it('同名节点稳定区分，无关节点插入不会改变路径', () => {
    const before = [{ name: '场景' }, { name: '灌木' }, { name: '灌木' }]
    const after = [{ name: '角色' }, ...before]

    expect(detailNodePath('root', before, 1)).toBe('root/%E7%81%8C%E6%9C%A8#1')
    expect(detailNodePath('root', before, 2)).toBe('root/%E7%81%8C%E6%9C%A8#2')
    expect(detailNodePath('root', after, 2)).toBe('root/%E7%81%8C%E6%9C%A8#1')
  })

  it('忽略随点位变化的 DC 和面数统计，保留节点业务身份', () => {
    expect(detailNodeIdentity({ name: '灌木 总DC:6 总面数:4' })).toBe('灌木')
    expect(detailNodeIdentity({ name: 'StaticMesh · DC 268 · 面数 152,430' })).toBe('StaticMesh')
    expect(detailNodeIdentity({ name: 'Total:当前画面总的DC和面数' }))
      .toBe('Total:当前画面总的DC和面数')

    expect(detailNodePath('root', [{ name: '灌木 总DC:6 总面数:4' }], 0))
      .toBe('root/%E7%81%8C%E6%9C%A8#1')
    expect(detailNodePath('root', [{ name: '灌木 总DC:9 总面数:11826' }], 0))
      .toBe('root/%E7%81%8C%E6%9C%A8#1')
  })
})
