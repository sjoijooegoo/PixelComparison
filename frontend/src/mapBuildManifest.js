function normalizedRelativePath(value) {
  const path = String(value || '').replace(/\\/g, '/').replace(/^\.\//, '')
  if (
    !path
    || path.startsWith('/')
    || /^[a-z]:/i.test(path)
    || path.split('/').some((part) => !part || part === '..')
  ) {
    return ''
  }
  return path
}

/**
 * 从新版 manifest 的 artifacts.map_build_data 中读取 JSON。
 * 未声明该 artifact 属于正常旧包；声明但缺文件时返回 missing，交给上报预览明确提示。
 */
export async function readMapBuildArtifact(manifest, files, manifestDir = '') {
  const spec = manifest?.artifacts?.map_build_data
  if (!spec) return { data: null, format: null, missing: '' }

  const relativePath = normalizedRelativePath(spec.path)
  if (!relativePath) {
    return { data: null, format: spec.format || 'map-build-data/v2', missing: spec.path || '(未提供路径)' }
  }
  const file = files.get(`${manifestDir}${relativePath}`)
  if (!file) {
    return { data: null, format: spec.format || 'map-build-data/v2', missing: relativePath }
  }
  let data
  try {
    data = JSON.parse(await file.text())
  } catch (error) {
    throw new Error(`烘培数据 JSON 解析失败：${error?.message || error}`)
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('烘培数据必须是 JSON 对象')
  }
  return {
    data,
    format: spec.format || 'map-build-data/v2',
    missing: '',
  }
}
