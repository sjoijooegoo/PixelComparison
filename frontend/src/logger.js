// 轻量前端日志:控制台打印(中文)+ 缓冲上报后端落盘(data/logs/frontend.log)
const buffer = []
let timer = null

function ts() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function emit(level, args) {
  const msg = args.map((a) => (typeof a === 'string' ? a : safe(a))).join(' ')
  const fn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log
  fn(`[${ts()}] ${level.toUpperCase()} ${msg}`)
  buffer.push({ level, msg, ts: new Date().toISOString() })
  if (level === 'error') flush()
  else schedule()
}

function safe(v) {
  try { return JSON.stringify(v) } catch { return String(v) }
}

function schedule() {
  if (timer) return
  timer = setTimeout(flush, 5000)
}

function flush() {
  if (timer) { clearTimeout(timer); timer = null }
  if (!buffer.length) return
  const logs = buffer.splice(0, buffer.length)
  // 不用 await:失败就算了,不影响前端
  fetch('/api/client-logs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ logs }),
    keepalive: true,
  }).catch(() => {})
}

export const logger = {
  info: (...a) => emit('info', a),
  warn: (...a) => emit('warn', a),
  error: (...a) => emit('error', a),
  install() {
    window.addEventListener('error', (e) => emit('error', ['未捕获错误:', e.message]))
    window.addEventListener('unhandledrejection', (e) =>
      emit('error', ['未处理的 Promise 拒绝:', e.reason?.message || e.reason]))
    window.addEventListener('beforeunload', flush)
  },
}
