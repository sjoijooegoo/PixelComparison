const QUALITY_LABELS = new Map([
  [5, '电影'], [4, '极致'], [3, '精美'],
  [2, '均衡'], [1, '流畅'], [0, '节能'],
])

export function qualityLabel(value) {
  if (value == null || value === '') return '——'
  const quality = Number(value)
  return QUALITY_LABELS.get(quality) || `画质 ${value}`
}

export function completeQualityRuns(batch) {
  const runs = Array.isArray(batch?.quality_runs) ? batch.quality_runs : []
  if (runs.length) {
    return runs
      .filter((run) => run?.is_complete)
      .slice()
      .sort((a, b) => Number(b.shading_quality) - Number(a.shading_quality))
  }
  // 兼容尚未返回 quality_runs 的旧接口响应。
  if (batch?.has_screenshots && batch?.shading_quality != null) {
    return [{
      shading_quality: Number(batch.shading_quality),
      is_complete: true,
      ready_screenshot_count: Number(batch.scene_count || 0),
    }]
  }
  return []
}

export function preferredPreviewQuality(batch) {
  const runs = completeQualityRuns(batch)
  return runs.find((run) => Number(run.shading_quality) === 5)?.shading_quality
    ?? runs[0]?.shading_quality
    ?? null
}

export function qualityColumnKey(column) {
  if (!column) return ''
  return String(column.column_id || `${column.id}:${column.shading_quality}`)
}

export function sameQualityColumn(left, right) {
  return Boolean(left && right && qualityColumnKey(left) === qualityColumnKey(right))
}
