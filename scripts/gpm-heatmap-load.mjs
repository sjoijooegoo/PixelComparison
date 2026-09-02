// 热力图主界面只读并发压测。
// 模拟多个用户持续切换平台/地图/画质、点位、整体/单点趋势，并加载地图与缩略图。
// 不访问设置接口，也不执行上传、删除或任何配置写入。
//
// 用法：
//   node scripts/gpm-heatmap-load.mjs --base http://127.0.0.1:5173 --users 10 --rounds 25

const DEFAULTS = {
  base: 'http://127.0.0.1:5173',
  branch: 'main',
  users: 10,
  rounds: 25,
  days: 14,
  timeout: 15000,
  think: 10,
}

function parseArgs(argv) {
  const result = { ...DEFAULTS }
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index]
    if (!token.startsWith('--')) throw new Error(`未知参数：${token}`)
    const key = token.slice(2)
    if (!(key in result)) throw new Error(`未知参数：${token}`)
    const value = argv[index + 1]
    if (value == null || value.startsWith('--')) throw new Error(`${token} 缺少值`)
    result[key] = ['users', 'rounds', 'days', 'timeout', 'think'].includes(key)
      ? Number(value)
      : value
    index += 1
  }
  result.base = String(result.base).replace(/\/$/, '')
  for (const key of ['users', 'rounds', 'timeout']) {
    if (!Number.isInteger(result[key]) || result[key] <= 0) {
      throw new Error(`--${key} 必须为正整数`)
    }
  }
  if (![7, 14, 30].includes(result.days)) throw new Error('--days 仅支持 7、14、30')
  if (!Number.isFinite(result.think) || result.think < 0) throw new Error('--think 不能小于 0')
  return result
}

const options = parseArgs(process.argv.slice(2))
const endpointStats = new Map()
const errors = []
const latestByUserScope = new Map()
let requestCount = 0
let responseBytes = 0

function statFor(name) {
  if (!endpointStats.has(name)) endpointStats.set(name, { durations: [], bytes: [], failures: 0 })
  return endpointStats.get(name)
}

function percentile(values, ratio) {
  if (!values.length) return 0
  const sorted = [...values].sort((left, right) => left - right)
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1)]
}

function rounded(value) {
  return Math.round(value * 10) / 10
}

function sleep(ms) {
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve()
}

function absoluteUrl(path) {
  return /^https?:\/\//i.test(path) ? path : `${options.base}${path.startsWith('/') ? '' : '/'}${path}`
}

async function request(name, path, { json = true } = {}) {
  const stat = statFor(name)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeout)
  const started = performance.now()
  let recorded = false
  let markedFailure = false
  try {
    const response = await fetch(absoluteUrl(path), {
      headers: { Accept: json ? 'application/json' : '*/*' },
      signal: controller.signal,
    })
    const body = new Uint8Array(await response.arrayBuffer())
    const duration = performance.now() - started
    requestCount += 1
    responseBytes += body.byteLength
    stat.durations.push(duration)
    stat.bytes.push(body.byteLength)
    recorded = true
    if (!response.ok) {
      stat.failures += 1
      markedFailure = true
      const text = new TextDecoder().decode(body).slice(0, 300)
      throw new Error(`${name} HTTP ${response.status}: ${text}`)
    }
    if (!json) {
      const type = response.headers.get('content-type') || ''
      if (!type.startsWith('image/')) throw new Error(`${name} 返回了非图片类型 ${type || '(empty)'}`)
      return { bytes: body.byteLength, contentType: type }
    }
    const type = response.headers.get('content-type') || ''
    if (!type.includes('application/json')) throw new Error(`${name} 返回了非 JSON 类型 ${type || '(empty)'}`)
    try {
      return JSON.parse(new TextDecoder().decode(body))
    } catch (error) {
      throw new Error(`${name} JSON 解析失败：${error.message}`)
    }
  } catch (error) {
    if (!recorded) {
      // fetch/超时异常没有响应体，仍计入调用统计。
      requestCount += 1
      stat.failures += 1
      stat.durations.push(performance.now() - started)
      stat.bytes.push(0)
    } else if (!markedFailure) {
      stat.failures += 1
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
}

function check(condition, message) {
  if (!condition) throw new Error(`数据校验失败：${message}`)
}

function query(params) {
  return new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)])).toString()
}

function scopesFromCatalog(catalog) {
  const scopes = []
  for (const map of catalog.maps || []) {
    if (!map.has_data) continue
    for (const platform of map.platform_qualities || []) {
      for (const quality of platform.shading_qualities || []) {
        scopes.push({
          mapName: map.value,
          platform: platform.platform,
          quality: Number(quality.value),
        })
      }
    }
  }
  return scopes
}

function validateFrame(frame, scope, userId) {
  check(frame?.map?.map_name === scope.mapName,
    `user${userId} frame 地图 ${frame?.map?.map_name} != ${scope.mapName}`)
  check(frame?.batch?.platform === scope.platform,
    `user${userId} frame 平台 ${frame?.batch?.platform} != ${scope.platform}`)
  check(Number(frame?.batch?.shading_quality) === scope.quality,
    `user${userId} frame 画质 ${frame?.batch?.shading_quality} != ${scope.quality}`)
  check(Array.isArray(frame.points) && frame.points.length > 0,
    `user${userId} frame 没有点位`)
  const pointIds = new Set()
  const pointIndexes = new Set()
  for (const point of frame.points) {
    check(!pointIds.has(point.id), `user${userId} frame 出现重复 point id ${point.id}`)
    check(!pointIndexes.has(String(point.index)), `user${userId} frame 出现重复点位序号 ${point.index}`)
    check(String(point.index) === String(point.screenshot_id),
      `user${userId} 点位 ${point.id} 的 index=${point.index} 与 screenshot_id=${point.screenshot_id} 不一致`)
    pointIds.add(point.id)
    pointIndexes.add(String(point.index))
  }

  const latestKey = `${userId}|${scope.mapName}|${scope.platform}|${scope.quality}`
  const capturedAt = Date.parse(frame.batch.captured_at)
  check(Number.isFinite(capturedAt), `user${userId} 批次时间不可解析：${frame.batch.captured_at}`)
  const previous = latestByUserScope.get(latestKey)
  check(previous == null || capturedAt >= previous,
    `user${userId} 最新批次时间倒退：${frame.batch.captured_at}`)
  latestByUserScope.set(latestKey, capturedAt)
}

function validateDetail(detail, frame, point, userId) {
  check(detail?.id === point.id, `user${userId} 详情 point id ${detail?.id} != ${point.id}`)
  check(detail?.map_name === frame.map.map_name,
    `user${userId} 详情地图 ${detail?.map_name} != ${frame.map.map_name}`)
  check(String(detail?.batch_id) === String(frame.batch.batch_id),
    `user${userId} 详情批次 ${detail?.batch_id} != ${frame.batch.batch_id}`)
  check(detail?.platform === frame.batch.platform,
    `user${userId} 详情平台 ${detail?.platform} != ${frame.batch.platform}`)
  check(Number(detail?.shading_quality) === Number(frame.batch.shading_quality),
    `user${userId} 详情画质 ${detail?.shading_quality} != ${frame.batch.shading_quality}`)
  check(String(detail?.index) === String(point.index),
    `user${userId} 详情序号 ${detail?.index} != ${point.index}`)
}

function validateTrend(trend, userId) {
  check(trend?.days === options.days, `user${userId} 趋势天数 ${trend?.days} != ${options.days}`)
  check(Array.isArray(trend.points), `user${userId} 趋势 points 不是数组`)
  let previous = -Infinity
  const keys = new Set()
  for (const point of trend.points) {
    const timestamp = Date.parse(point.captured_at)
    check(Number.isFinite(timestamp), `user${userId} 趋势时间不可解析：${point.captured_at}`)
    check(timestamp >= previous, `user${userId} 趋势点未按时间升序排列`)
    const key = `${point.batch_id}|${point.captured_at}`
    check(!keys.has(key), `user${userId} 趋势出现重复点 ${key}`)
    previous = timestamp
    keys.add(key)
  }
}

async function runUser(userId, scopes) {
  const loadedMapImages = new Set()
  for (let round = 0; round < options.rounds; round += 1) {
    const scope = scopes[(userId - 1 + round * 7) % scopes.length]
    const context = `user${userId}/round${round + 1}/${scope.mapName}/${scope.platform}/q${scope.quality}`
    try {
      if (round > 0 && round % 5 === 0) {
        const catalog = await request('catalog', `/api/gpm-heatmaps/catalog?${query({ branch_tag: options.branch })}`)
        check(scopesFromCatalog(catalog).length > 0, `${context} 刷新目录后没有可用数据范围`)
      }

      const frame = await request(
        'frame',
        `/api/gpm-heatmaps/maps/${encodeURIComponent(scope.mapName)}/frame?${query({
          branch_tag: options.branch,
          platform: scope.platform,
          shading_quality: scope.quality,
        })}`,
      )
      validateFrame(frame, scope, userId)
      const point = frame.points[(userId * 17 + round * 13) % frame.points.length]
      const trendPath = round % 2 === 0
        ? `/api/gpm-heatmaps/maps/${encodeURIComponent(scope.mapName)}/trends?${query({
          branch_tag: options.branch,
          platform: scope.platform,
          shading_quality: scope.quality,
          days: options.days,
        })}`
        : `/api/gpm-heatmaps/points/${encodeURIComponent(point.id)}/trends?${query({ days: options.days })}`
      const trendName = round % 2 === 0 ? 'map-trend' : 'point-trend'

      const jobs = [
        request('point-detail', `/api/gpm-heatmaps/points/${encodeURIComponent(point.id)}`),
        request(trendName, trendPath),
        request('thumbnail', point.thumbnail_url, { json: false }),
      ]
      const mapImageKey = `${scope.mapName}|${frame.map_config?.image_url || ''}`
      if (frame.map_config?.image_url && !loadedMapImages.has(mapImageKey)) {
        loadedMapImages.add(mapImageKey)
        jobs.push(request('map-image', frame.map_config.image_url, { json: false }))
      }
      const [detail, trend] = await Promise.all(jobs)
      validateDetail(detail, frame, point, userId)
      validateTrend(trend, userId)
    } catch (error) {
      errors.push({ context, message: error?.message || String(error) })
    }
    await sleep(options.think)
  }
}

function catalogSnapshot(catalog) {
  return new Map((catalog.maps || []).map((map) => [map.value, {
    batchCount: Number(map.batch_count || 0),
    latestAt: map.latest_at || null,
  }]))
}

const startedAt = performance.now()
const initialCatalog = await request(
  'catalog', `/api/gpm-heatmaps/catalog?${query({ branch_tag: options.branch })}`,
)
const scopes = scopesFromCatalog(initialCatalog)
if (!scopes.length) throw new Error(`分支 ${options.branch} 没有可压测的热力图数据`)
const initialSnapshot = catalogSnapshot(initialCatalog)

await Promise.all(Array.from({ length: options.users }, (_, index) => runUser(index + 1, scopes)))

const finalCatalog = await request(
  'catalog', `/api/gpm-heatmaps/catalog?${query({ branch_tag: options.branch })}`,
)
const finalSnapshot = catalogSnapshot(finalCatalog)
const changedMaps = []
for (const [mapName, after] of finalSnapshot) {
  const before = initialSnapshot.get(mapName)
  if (!before || before.batchCount !== after.batchCount || before.latestAt !== after.latestAt) {
    changedMaps.push({ mapName, before: before || null, after })
  }
}

const duration = performance.now() - startedAt
console.log('\n=== GPM 热力图主界面只读并发压测 ===')
console.log(`base=${options.base} branch=${options.branch} users=${options.users} rounds=${options.rounds}`)
console.log(`数据范围=${scopes.length} 总耗时=${rounded(duration / 1000)}s 请求=${requestCount} RPS=${rounded(requestCount / (duration / 1000))}`)
console.log(`响应体=${rounded(responseBytes / 1024 / 1024)}MB 错误=${errors.length} 压测期间数据变化地图=${changedMaps.length}`)
console.log('')
console.log('endpoint        count fail p50(ms) p95(ms) p99(ms) max(ms) avg(KB)')
for (const [name, stat] of [...endpointStats.entries()].sort(([left], [right]) => left.localeCompare(right))) {
  const averageBytes = stat.bytes.reduce((total, value) => total + value, 0) / Math.max(stat.bytes.length, 1)
  const columns = [
    name.padEnd(15),
    String(stat.durations.length).padStart(5),
    String(stat.failures).padStart(4),
    String(rounded(percentile(stat.durations, 0.50))).padStart(7),
    String(rounded(percentile(stat.durations, 0.95))).padStart(7),
    String(rounded(percentile(stat.durations, 0.99))).padStart(7),
    String(rounded(Math.max(...stat.durations, 0))).padStart(7),
    String(rounded(averageBytes / 1024)).padStart(7),
  ]
  console.log(columns.join(' '))
}

if (changedMaps.length) {
  console.log('\n压测期间检测到的新上报/覆盖：')
  for (const item of changedMaps) console.log(`  ${item.mapName}: ${JSON.stringify(item.before)} -> ${JSON.stringify(item.after)}`)
}
if (errors.length) {
  console.log('\n错误（最多显示 30 条）：')
  for (const error of errors.slice(0, 30)) console.log(`  [${error.context}] ${error.message}`)
}

process.exitCode = errors.length ? 1 : 0
