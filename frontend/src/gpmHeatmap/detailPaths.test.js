import { describe, expect, it } from 'vitest'

import { detailNodePath } from './detailPaths'

describe('GPM detail semantic paths', () => {
  it('同名节点稳定区分，无关节点插入不会改变路径', () => {
    const before = [{ name: '场景' }, { name: '灌木' }, { name: '灌木' }]
    const after = [{ name: '角色' }, ...before]

    expect(detailNodePath('root', before, 1)).toBe('root/%E7%81%8C%E6%9C%A8#1')
    expect(detailNodePath('root', before, 2)).toBe('root/%E7%81%8C%E6%9C%A8#2')
    expect(detailNodePath('root', after, 2)).toBe('root/%E7%81%8C%E6%9C%A8#1')
  })
})
