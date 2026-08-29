import { createMapProjection } from './mapProjection'

export function projectedPointStyle(map, position) {
  try {
    const point = createMapProjection(
      map,
      { left: 0, top: 0, width: 100, height: 100 },
    ).project(position)
    return { left: `${point.x}%`, top: `${point.y}%`, inBounds: point.inBounds }
  } catch {
    return null
  }
}
