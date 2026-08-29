function nodeName(node) {
  return String(node?.name || '未命名数据')
}

export function detailNodeSegment(nodes, index) {
  const name = nodeName(nodes?.[index])
  let occurrence = 0
  for (let current = 0; current <= index; current += 1) {
    if (nodeName(nodes?.[current]) === name) occurrence += 1
  }
  return `${encodeURIComponent(name)}#${occurrence}`
}

export function detailNodePath(parentPath, nodes, index) {
  const segment = detailNodeSegment(nodes, index)
  return parentPath ? `${parentPath}/${segment}` : segment
}
