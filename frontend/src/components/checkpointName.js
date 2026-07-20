const CHECKPOINT_INDEX_PATTERN = /^(.+)_([0-9]{4})$/

export function splitCheckpointName(value) {
  const fullName = typeof value === 'string' ? value : ''
  const match = CHECKPOINT_INDEX_PATTERN.exec(fullName)

  if (!match) return { name: fullName, index: '' }
  return { name: match[1], index: match[2] }
}
