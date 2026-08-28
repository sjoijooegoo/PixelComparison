const MIN_SEGMENTS = 2
const MAX_SEGMENTS = 10
const DEFAULT_COLORS = ['#52e817', '#b7f400', '#ffb20a', '#ff4a0a', '#ff1111']
const DEFAULT_THRESHOLDS = [100, 200, 300, 400]
const NUMBER_PATTERN = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?'
const COMPARISON = new RegExp(`^(<=|>=|<|>)\\s*(${NUMBER_PATTERN})$`)
const HEX_COLOR = /^#[0-9a-f]{6}$/i

export class ScaleExpressionError extends Error {
  constructor(message) {
    super(message)
    this.name = 'ScaleExpressionError'
  }
}

function numberText(value) {
  return Object.is(value, -0) || value === 0 ? '0' : String(value)
}

function parseExpression(expression, rowNumber) {
  const text = String(expression || '').trim().replaceAll('≤', '<=').replaceAll('≥', '>=')
  if (!text) throw new ScaleExpressionError(`颜色段 ${rowNumber} 的区间表达式不能为空`)
  const parts = text.split('&').map((part) => part.trim())
  if (parts.length < 1 || parts.length > 2 || parts.some((part) => !part)) {
    throw new ScaleExpressionError(
      `颜色段 ${rowNumber} 的表达式格式不正确；示例：<365 或 >=365 & <390`,
    )
  }

  let lower = null
  let upper = null
  parts.forEach((part) => {
    const match = part.match(COMPARISON)
    if (!match) {
      throw new ScaleExpressionError(
        `颜色段 ${rowNumber} 的表达式“${text}”无法解析；仅支持 <、<=、>、>= 和 &`,
      )
    }
    const [, operator, rawNumber] = match
    const value = Number(rawNumber)
    if (!Number.isFinite(value)) {
      throw new ScaleExpressionError(`颜色段 ${rowNumber} 的边界必须是有限数字`)
    }
    if (operator.startsWith('>')) {
      if (lower) throw new ScaleExpressionError(`颜色段 ${rowNumber} 只能包含一个下界`)
      lower = { value, inclusive: operator === '>=' }
    } else {
      if (upper) throw new ScaleExpressionError(`颜色段 ${rowNumber} 只能包含一个上界`)
      upper = { value, inclusive: operator === '<=' }
    }
  })
  if (lower && upper) {
    if (lower.value > upper.value) {
      throw new ScaleExpressionError(`颜色段 ${rowNumber} 的下界不能大于上界`)
    }
    if (lower.value === upper.value) {
      throw new ScaleExpressionError(`颜色段 ${rowNumber} 不能是空区间或单点区间`)
    }
  }
  return { lower, upper }
}

function canonicalExpression(interval) {
  const terms = []
  if (interval.lower) {
    terms.push(`${interval.lower.inclusive ? '>=' : '>'}${numberText(interval.lower.value)}`)
  }
  if (interval.upper) {
    terms.push(`${interval.upper.inclusive ? '<=' : '<'}${numberText(interval.upper.value)}`)
  }
  return terms.join(' & ')
}

export function compileScaleSegments(value) {
  if (!Array.isArray(value) || value.length < MIN_SEGMENTS || value.length > MAX_SEGMENTS) {
    throw new ScaleExpressionError(
      `颜色标尺必须包含 ${MIN_SEGMENTS} 到 ${MAX_SEGMENTS} 个颜色段`,
    )
  }

  const intervals = value.map((raw, index) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      throw new ScaleExpressionError(`颜色段 ${index + 1} 必须是对象`)
    }
    const color = String(raw.color || '').trim().toLowerCase()
    if (!HEX_COLOR.test(color)) {
      throw new ScaleExpressionError(`颜色段 ${index + 1} 的颜色必须使用 #RRGGBB 格式`)
    }
    return { color, ...parseExpression(raw.expression, index + 1) }
  })
  const orderedIntervals = [...intervals].sort((left, right) => {
    if (!left.lower) return -1
    if (!right.lower) return 1
    if (left.lower.value !== right.lower.value) return left.lower.value - right.lower.value
    return Number(right.lower.inclusive) - Number(left.lower.inclusive)
  })

  if (orderedIntervals[0].lower) {
    throw new ScaleExpressionError('第一个颜色段必须没有下界，例如 <365')
  }
  if (orderedIntervals.at(-1).upper) {
    throw new ScaleExpressionError('最后一个颜色段必须没有上界，例如 >=440')
  }

  orderedIntervals.slice(0, -1).forEach((left, index) => {
    const right = orderedIntervals[index + 1]
    if (!left.upper) {
      throw new ScaleExpressionError(`区间“${canonicalExpression(left)}”会覆盖其后的颜色段`)
    }
    if (!right.lower) throw new ScaleExpressionError('只能有一个没有下界的颜色段')
    if (left.upper.value < right.lower.value) {
      throw new ScaleExpressionError(
        `${numberText(left.upper.value)} 到 ${numberText(right.lower.value)} 之间没有颜色覆盖`,
      )
    }
    if (left.upper.value > right.lower.value) {
      throw new ScaleExpressionError(`区间在 ${numberText(right.lower.value)} 附近发生重叠`)
    }
    if (left.upper.inclusive && right.lower.inclusive) {
      throw new ScaleExpressionError(
        `边界 ${numberText(left.upper.value)} 同时属于两个颜色段`,
      )
    }
    if (!left.upper.inclusive && !right.lower.inclusive) {
      throw new ScaleExpressionError(
        `边界 ${numberText(left.upper.value)} 不属于任何颜色段；请将一侧改为 <= 或 >=`,
      )
    }
  })

  return {
    segments: intervals.map((interval) => ({
      color: interval.color,
      expression: canonicalExpression(interval),
    })),
    thresholds: orderedIntervals.slice(0, -1).map((interval) => interval.upper.value),
    colors: orderedIntervals.map((interval) => interval.color),
  }
}

export function segmentsFromLegacy(thresholds, colors, direction = 'lower_is_better') {
  let safeColors = Array.isArray(colors) && colors.length >= MIN_SEGMENTS && colors.length <= MAX_SEGMENTS
    ? colors.map((color) => String(color).trim().toLowerCase())
    : [...DEFAULT_COLORS]
  let safeThresholds = Array.isArray(thresholds) && thresholds.length === safeColors.length - 1
    ? thresholds.map(Number)
    : [...DEFAULT_THRESHOLDS]
  if (safeThresholds.length !== safeColors.length - 1
    || !safeThresholds.every(Number.isFinite)
    || safeThresholds.some((value, index) => index && value <= safeThresholds[index - 1])) {
    safeColors = [...DEFAULT_COLORS]
    safeThresholds = [...DEFAULT_THRESHOLDS]
  }
  if (direction === 'higher_is_better') safeColors.reverse()
  return compileScaleSegments(safeColors.map((color, index) => {
    let expression
    if (index === 0) expression = `<${numberText(safeThresholds[0])}`
    else if (index === safeColors.length - 1) expression = `>=${numberText(safeThresholds.at(-1))}`
    else expression = `>=${numberText(safeThresholds[index - 1])} & <${numberText(safeThresholds[index])}`
    return { color, expression }
  })).segments
}

export function defaultScaleSegments(colors = DEFAULT_COLORS) {
  const safeColors = Array.isArray(colors) && colors.length === DEFAULT_COLORS.length
    ? colors : DEFAULT_COLORS
  return segmentsFromLegacy(DEFAULT_THRESHOLDS, safeColors)
}
