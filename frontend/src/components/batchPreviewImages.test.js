import { describe, expect, it } from 'vitest'

import { batchPreviewImage } from './batchPreviewImages'

describe('batchPreviewImage', () => {
  it('卡片使用缩略图而灯箱保留原图地址', () => {
    expect(batchPreviewImage('/images/batches/7/shot.png?v=abc')).toEqual({
      thumbnailUrl: '/thumb/batches/7/shot.png?v=abc&strict=true',
      originalUrl: '/images/batches/7/shot.png?v=abc',
    })
  })
})
