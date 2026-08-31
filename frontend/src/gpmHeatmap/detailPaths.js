const TRAILING_AGGREGATES = /(?:\s*[·|]\s*|\s+)(?:总\s*)?DC\s*[:：]?\s*[-+]?\d[\d,.]*(?:\s*(?:[·|]\s*)?(?:总\s*)?(?:面数|Tris|Triangles)\s*[:：]?\s*[-+]?\d[\d,.]*)?\s*$/iu

export function detailNodeIdentity(node) {
  const name = String(node?.name || '未命名数据')
  const stableName = name.replace(TRAILING_AGGREGATES, '').trim()
  return stableName || name
}

export function detailNodeSegment(nodes, index) {
  const name = detailNodeIdentity(nodes?.[index])
  let occurrence = 0
  for (let current = 0; current <= index; current += 1) {
    if (detailNodeIdentity(nodes?.[current]) === name) occurrence += 1
  }
  return `${encodeURIComponent(name)}#${occurrence}`
}

export function detailNodePath(parentPath, nodes, index) {
  const segment = detailNodeSegment(nodes, index)
  return parentPath ? `${parentPath}/${segment}` : segment
}
