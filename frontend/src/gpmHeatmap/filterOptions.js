import { SHADING_QUALITY_OPTIONS } from '../store'

export const GPM_DEFAULT_PLATFORMS = ['IOS', 'Android', 'Windows']

function optionValue(item) {
  return item?.value ?? item
}

export function mergeGpmPlatforms(...sources) {
  return [...new Set([
    ...GPM_DEFAULT_PLATFORMS,
    ...sources.flat().map(optionValue).filter(Boolean),
  ])]
}

export function mergeGpmQualities(...sources) {
  const known = new Map(SHADING_QUALITY_OPTIONS.map((item) => [item.value, item]))
  for (const item of sources.flat()) {
    const value = Number(optionValue(item))
    if (!Number.isInteger(value)) continue
    known.set(value, typeof item === 'object' ? item : {
      value,
      label: `画质 ${value}`,
    })
  }
  return [...known.values()].sort((left, right) => Number(right.value) - Number(left.value))
}

export function gpmMapValues(items) {
  return (items || []).map(optionValue).filter(Boolean)
}
