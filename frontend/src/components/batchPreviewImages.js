import { thumbUrl } from '../api'

// 卡片阶段只下载缩略图；Arco 灯箱在用户点击后才读取 previewProps.src 原图。
export function batchPreviewImage(originalUrl) {
  const thumbnail = thumbUrl(originalUrl)
  const separator = thumbnail?.includes('?') ? '&' : '?'
  return {
    thumbnailUrl: thumbnail ? `${thumbnail}${separator}strict=true` : thumbnail,
    originalUrl,
  }
}
