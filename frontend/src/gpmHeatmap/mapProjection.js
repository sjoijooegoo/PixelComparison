function finiteNumber(value, label) {
  const number = Number(value)
  if (!Number.isFinite(number)) throw new Error(`${label} 必须是有限数字`)
  return number
}

export function containedImageRect(containerWidth, containerHeight, imageWidth, imageHeight) {
  const width = finiteNumber(containerWidth, '容器宽度')
  const height = finiteNumber(containerHeight, '容器高度')
  const naturalWidth = finiteNumber(imageWidth, '图片宽度')
  const naturalHeight = finiteNumber(imageHeight, '图片高度')
  if (width <= 0 || height <= 0 || naturalWidth <= 0 || naturalHeight <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 }
  }
  const scale = Math.min(width / naturalWidth, height / naturalHeight)
  const renderedWidth = naturalWidth * scale
  const renderedHeight = naturalHeight * scale
  return {
    left: (width - renderedWidth) / 2,
    top: (height - renderedHeight) / 2,
    width: renderedWidth,
    height: renderedHeight,
  }
}

export function createMapProjection(config, renderedRect) {
  const originX = finiteNumber(config?.origin?.[0], '地图起点 X')
  const originY = finiteNumber(config?.origin?.[1], '地图起点 Y')
  const rangeX = finiteNumber(config?.range?.[0], '地图范围 X')
  const rangeY = finiteNumber(config?.range?.[1], '地图范围 Y')
  const left = finiteNumber(renderedRect?.left, '渲染区域 left')
  const top = finiteNumber(renderedRect?.top, '渲染区域 top')
  const width = finiteNumber(renderedRect?.width, '渲染区域宽度')
  const height = finiteNumber(renderedRect?.height, '渲染区域高度')
  if (rangeX <= 0 || rangeY <= 0 || width < 0 || height < 0) {
    throw new Error('地图坐标范围和渲染尺寸必须有效')
  }
  const xSign = config?.x_reverse ? -1 : 1
  // 上报的朝向向量使用“向上为正”的 Y 轴约定；Canvas 屏幕坐标则向下为正。
  // 地图点位位置仍按地图配置映射，只有朝向需要额外翻转屏幕 Y 轴。
  const ySign = config?.y_reverse ? -1 : 1

  function normalized(position) {
    let x = (finiteNumber(position?.[0], '点位 X') - originX) / rangeX
    let y = (finiteNumber(position?.[1], '点位 Y') - originY) / rangeY
    if (config?.x_reverse) x = 1 - x
    if (!config?.y_reverse) y = 1 - y
    return { x, y }
  }

  return {
    project(position) {
      const point = normalized(position)
      return {
        x: left + point.x * width,
        y: top + point.y * height,
        inBounds: point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1,
      }
    },
    projectDirection(direction) {
      const dx = finiteNumber(direction?.[0], '方向 X') * xSign
      const dy = finiteNumber(direction?.[1], '方向 Y') * ySign
      const length = Math.hypot(dx, dy) || 1
      return { x: dx / length, y: dy / length }
    },
    unproject(point) {
      let nx = width ? (finiteNumber(point?.x, '屏幕 X') - left) / width : 0
      let ny = height ? (finiteNumber(point?.y, '屏幕 Y') - top) / height : 0
      if (config?.x_reverse) nx = 1 - nx
      if (!config?.y_reverse) ny = 1 - ny
      return [originX + nx * rangeX, originY + ny * rangeY]
    },
  }
}
