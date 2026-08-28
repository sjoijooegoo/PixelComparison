export function projectedPointStyle(map, position) {
  const originX = Number(map?.origin?.[0])
  const originY = Number(map?.origin?.[1])
  const rangeX = Number(map?.range?.[0])
  const rangeY = Number(map?.range?.[1])
  if (![originX, originY, rangeX, rangeY, Number(position?.[0]), Number(position?.[1])]
    .every(Number.isFinite) || rangeX <= 0 || rangeY <= 0) return null
  let x = (Number(position[0]) - originX) / rangeX
  let y = (Number(position[1]) - originY) / rangeY
  if (map.x_reverse) x = 1 - x
  if (!map.y_reverse) y = 1 - y
  return { left: `${x * 100}%`, top: `${y * 100}%`, inBounds: x >= 0 && x <= 1 && y >= 0 && y <= 1 }
}
