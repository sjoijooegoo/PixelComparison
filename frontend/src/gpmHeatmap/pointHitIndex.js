const DEFAULT_CELL_SIZE = 32

function cellKey(x, y) {
  return `${x}:${y}`
}

/**
 * Build a small spatial index for canvas hit testing. Point rendering may scale to
 * thousands of samples, while pointer movement should only inspect nearby cells.
 */
export function createPointHitIndex(points, cellSize = DEFAULT_CELL_SIZE) {
  const safeCellSize = Number.isFinite(cellSize) && cellSize > 0
    ? cellSize
    : DEFAULT_CELL_SIZE
  const buckets = new Map()

  for (const point of points || []) {
    const radius = Math.max(0, Number(point.hit) || 0)
    const minimumX = Math.floor((point.x - radius) / safeCellSize)
    const maximumX = Math.floor((point.x + radius) / safeCellSize)
    const minimumY = Math.floor((point.y - radius) / safeCellSize)
    const maximumY = Math.floor((point.y + radius) / safeCellSize)
    for (let cellX = minimumX; cellX <= maximumX; cellX += 1) {
      for (let cellY = minimumY; cellY <= maximumY; cellY += 1) {
        const key = cellKey(cellX, cellY)
        const bucket = buckets.get(key)
        if (bucket) bucket.push(point)
        else buckets.set(key, [point])
      }
    }
  }

  return {
    find(x, y) {
      const candidates = buckets.get(cellKey(
        Math.floor(x / safeCellSize),
        Math.floor(y / safeCellSize),
      )) || []
      let nearest = null
      let nearestSquaredDistance = Infinity
      for (const point of candidates) {
        const deltaX = x - point.x
        const deltaY = y - point.y
        const squaredDistance = deltaX * deltaX + deltaY * deltaY
        if (squaredDistance <= point.hit * point.hit
          && squaredDistance < nearestSquaredDistance) {
          nearest = point
          nearestSquaredDistance = squaredDistance
        }
      }
      return nearest
    },
  }
}
