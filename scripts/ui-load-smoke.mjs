// 多人并发界面冒烟:开 N 个浏览器上下文模拟多人同时使用,
// 各自浏览 批次列表 -> 列表图(滚动) -> 对比结果,收集 console/page 报错与各页加载耗时。
// 用法: node scripts/ui-load-smoke.mjs [base] [scene] [users]
//   node scripts/ui-load-smoke.mjs http://localhost:5173 Village_Dimension_Main 6
import { pathToFileURL } from 'url'

const PW = 'C:/WorkSpace/jm/node_modules/playwright/index.js'
const { chromium } = (await import(pathToFileURL(PW).href)).default

const base = process.argv[2] || 'http://localhost:5173'
const scene = process.argv[3] || 'Village_Dimension_Main'
const users = Number(process.argv[4] || 6)

const pct = (arr, q) => {
  if (!arr.length) return 0
  const s = [...arr].sort((a, b) => a - b)
  return Math.round(s[Math.min(s.length - 1, Math.floor(s.length * q))])
}

const browser = await chromium.launch()
const errors = []          // {user, type, text}
const nav = {}             // page -> [ms]
const note = (page, ms) => (nav[page] ||= []).push(ms)

async function go(p, url, label, u) {
  const t0 = Date.now()
  await p.goto(url, { waitUntil: 'networkidle' }).catch((e) => errors.push({ user: u, type: 'nav', text: `${label}: ${e.message}` }))
  note(label, Date.now() - t0)
}

async function user(u) {
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 850 } })
  const p = await ctx.newPage()
  p.on('console', (m) => { if (m.type() === 'error') errors.push({ user: u, type: 'console', text: m.text().slice(0, 200) }) })
  p.on('pageerror', (e) => errors.push({ user: u, type: 'pageerror', text: (e.message || String(e)).slice(0, 200) }))
  for (let r = 0; r < 3; r++) {              // 多轮来回切换,模拟持续操作
    await go(p, `${base}/batches`, 'batches', u)
    await p.waitForTimeout(150)
    await go(p, `${base}/batches/${encodeURIComponent(scene)}`, 'grid', u)
    // 在列表图里滚动 + 拖拽一下
    await p.evaluate(() => { const el = document.querySelector('.grid-scroll'); if (el) el.scrollTop = 300 }).catch(() => {})
    await p.waitForTimeout(150)
    await go(p, `${base}/comparison`, 'comparison', u)
    await p.waitForTimeout(150)
  }
  await ctx.close()
}

const t0 = Date.now()
await Promise.all(Array.from({ length: users }, (_, i) => user(i + 1)))
await browser.close()

console.log(`\n=== UI 并发冒烟: ${users} 个上下文, base=${base}, scene=${scene}, 总耗时 ${((Date.now() - t0) / 1000).toFixed(1)}s ===`)
for (const [page, ms] of Object.entries(nav)) {
  console.log(`[${page}] loads=${ms.length} p50=${pct(ms, 0.5)}ms p95=${pct(ms, 0.95)}ms max=${Math.max(...ms)}ms`)
}
console.log(`错误数: ${errors.length}`)
for (const e of errors.slice(0, 20)) console.log(`  user${e.user} [${e.type}] ${e.text}`)
process.exit(errors.length ? 1 : 0)
