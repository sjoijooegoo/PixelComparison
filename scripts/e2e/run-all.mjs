// 前端交互 E2E(Playwright)。对「正在运行」的应用跑,动态发现场景/批次,不依赖固定 ID,不改库。
// 需要后端 + 前端在跑(默认 http://localhost:5173)。
// 用法: node scripts/e2e/run-all.mjs [base]
import { pathToFileURL } from 'url'

const PW = 'C:/WorkSpace/jm/node_modules/playwright/index.js'
const { chromium } = (await import(pathToFileURL(PW).href)).default
const base = (process.argv[2] || 'http://localhost:5173').replace(/\/$/, '')

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`  ${ok ? '✓' : '✗'} ${name}${detail ? ' — ' + detail : ''}`) }
const api = async (p) => (await fetch(base + p)).json()
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function waitFor(fn, ms = 15000, step = 200) {
  const end = Date.now() + ms
  while (Date.now() < end) { if (await fn()) return true; await sleep(step) }
  return false
}

// 找一个「列表图里能显示 >=2 个批次」的场景(受默认近七天筛选影响,故用 UI 判定)
async function pickGridScenes(page) {
  const meta = await api('/api/meta')
  const found = []
  for (const s of meta.scene_ids || []) {
    await page.goto(`${base}/batches/${encodeURIComponent(s)}`, { waitUntil: 'networkidle' }).catch(() => {})
    await sleep(300)
    const n = await page.locator('.role-btn').count().catch(() => 0)
    if (n >= 2) found.push({ scene: s, cols: n })
    if (found.length >= 2) break
  }
  return found
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 } })
const page = await ctx.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(e.message))

try {
  const scenes = await pickGridScenes(page)
  if (!scenes.length) {
    check('前置:找到含≥2批次的场景', false, '当前数据里没有(近七天内)满足的场景,E2E 无法继续')
    throw new Error('no usable scene')
  }
  const scene = scenes[0].scene
  console.log(`\n使用场景: ${scene}（${scenes[0].cols} 批次）`)

  // ---- T1 列表图:角色选择 / 高亮 / 取消 ----
  console.log('\n[T1] 列表图角色选择')
  await page.goto(`${base}/batches/${encodeURIComponent(scene)}`, { waitUntil: 'networkidle' })
  await sleep(400)
  await page.locator('.role-btn').nth(0).click()        // 第一次:设为基线
  check('点第一列后高亮为基线', await page.locator('.role-btn').nth(0).evaluate((e) => e.classList.contains('on')))
  await page.locator('.role-btn').nth(1).click()        // 第二次:设为对比
  check('点第二列后高亮为对比', await page.locator('.role-btn').nth(1).evaluate((e) => e.classList.contains('on')))
  check('两侧选定后表头出现 VS 卡片', await page.locator('.heat-cmp').count() === 1)
  await page.locator('.role-btn').nth(0).click()        // 再点一次取消
  check('再点取消高亮', !(await page.locator('.role-btn').nth(0).evaluate((e) => e.classList.contains('on'))))
  check('取消后 VS 卡片消失', await page.locator('.heat-cmp').count() === 0)

  // ---- T2 差异列:发起对比就地计算并填充 ----
  console.log('\n[T2] 差异列发起对比(就地计算)')
  await page.locator('.role-btn').nth(0).click()
  await page.locator('.role-btn').nth(1).click()
  await sleep(500)
  const urlBeforeCompare = page.url()
  const btn = page.locator('.heat-title .arco-btn')
  if (await btn.count()) {
    await btn.click()
    const done = await waitFor(async () => (await page.locator('.heat-title').innerText()).includes('差异对比'), 60000)
    check('点「发起对比」后表头回到「差异对比」(计算完成)', done)
  } else {
    check('该对已有缓存,直接显示「差异对比」', (await page.locator('.heat-title').innerText()).includes('差异对比'))
  }
  check('发起对比后停留在列表图(未跳转)', page.url() === urlBeforeCompare)

  // ---- T3 拖拽平移 + 单击放大 ----
  console.log('\n[T3] 拖拽平移 / 单击放大')
  const dragScroll = async (locator) => {
    const box = await locator.boundingBox()
    if (!box) return null
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2
    await page.locator('.grid-scroll').evaluate((el) => { el.scrollLeft = 0 })
    await page.mouse.move(cx, cy); await page.mouse.down()
    await page.evaluate(({ x, y }) => window.dispatchEvent(new MouseEvent('mousemove', { clientX: x - 150, clientY: y, bubbles: true })), { x: cx, y: cy })
    const sl = await page.locator('.grid-scroll').evaluate((el) => el.scrollLeft)
    await page.mouse.up()
    return sl
  }
  const maxScroll = await page.locator('.grid-scroll').evaluate((el) => el.scrollWidth - el.clientWidth)
  check('表头拖拽不平移', (await dragScroll(page.locator('.head').nth(1))) === 0)
  if (maxScroll > 10) {
    check('图片区拖拽可平移', (await dragScroll(page.locator('.imgcell .thumb').first())) > 0)
  } else {
    check('图片区拖拽可平移', true, '当前列宽未溢出,跳过(非失败)')
  }
  await page.locator('.imgcell .thumb').first().click()
  const opened = await waitFor(async () => (await page.locator('.arco-image-preview').count()) > 0, 5000)
  check('单击图片打开放大灯箱', opened)
  if (opened) {
    const src0 = await page.locator('.arco-image-preview img').first().getAttribute('src').catch(() => '')
    await page.keyboard.press('ArrowRight'); await sleep(400)
    const src1 = await page.locator('.arco-image-preview img').first().getAttribute('src').catch(() => '')
    check('放大后方向键可切换图片', !!src1 && src1 !== src0, src1 && src1.includes('/heatmaps/') ? '已切到差异热力图' : '')
    await page.keyboard.press('Escape'); await sleep(300)
  }

  // ---- T7 列头「差异对比」跳转 + 深链刷新 + 历史菜单走路由 ----
  // 承接 T1–T3:仍在列表图、首两列已选为基线/对比。确保这对已缓存后,测列头跳转。
  console.log('\n[T7] 差异对比列头跳转 / 深链 / 历史切换路由')
  const idOf = (u) => (u.match(/\/comparison\/(\d+)/) || [])[1] || null
  const linkN = () => page.locator('.heat-title-link').count()
  const btnN = () => page.locator('.heat-title .arco-btn').count()
  // 角色按钮是「再点取消」的开关,前序用例可能只剩单选;先清空再干净地选两列(col0=基线、col1=对比)
  while (await page.locator('.role-btn.on').count()) { await page.locator('.role-btn.on').first().click(); await sleep(150) }
  await page.locator('.role-btn').nth(0).click()
  await page.locator('.role-btn').nth(1).click()
  await sleep(400)
  // 先等 lookup 结算:列头要么是可点链接(已缓存),要么是「发起对比」按钮(未缓存)
  await waitFor(async () => (await linkN()) + (await btnN()) > 0, 10000)
  let linkReady = (await linkN()) > 0
  if (!linkReady && (await btnN())) {            // 未缓存:先就地算一次,再等链接出现
    await page.locator('.heat-title .arco-btn').click()
    linkReady = await waitFor(async () => (await linkN()) > 0, 60000)
  }
  check('缓存命中时列头「差异对比」可点击', linkReady)
  if (linkReady) {
    await page.locator('.heat-title-link').click()
    const navOk = await waitFor(async () => !!idOf(page.url()), 8000)
    const cid = idOf(page.url())
    check('点击后跳到 /comparison/:id', navOk, page.url().replace(base, ''))
    const sumOk = await waitFor(async () => (await page.locator('.summary .pair-trigger').count()) > 0, 8000)
    check('跳转后对比结果页加载出该对比', sumOk)

    // 深链刷新:整页 reload 后仍停在同一条对比(URL 不变 + 摘要在)
    await page.reload({ waitUntil: 'networkidle' })
    const keep = await waitFor(async () => (await page.locator('.summary .pair-trigger').count()) > 0, 8000)
    check('刷新后仍停在同一对比(深链)', keep && idOf(page.url()) === cid, `id=${idOf(page.url())}`)

    // 历史菜单切换:点不同历史项后 URL 的 id 应随之改变(需≥2条历史)
    await page.locator('.pair-trigger').click(); await sleep(300)
    const items = page.locator('.hist-item:not(.active)')
    if (await items.count()) {
      await items.first().click()
      const changed = await waitFor(async () => { const n = idOf(page.url()); return n && n !== cid }, 8000)
      check('历史菜单切换后 URL 的 id 同步变化', changed, `${cid} -> ${idOf(page.url())}`)
    } else {
      check('历史菜单切换走路由', true, '历史仅一条,跳过(非失败)')
    }
  }

  // ---- T4 对比结果页:一键换向 ----
  console.log('\n[T4] 对比结果页换向(基线↔对比)')
  await page.goto(`${base}/comparison`, { waitUntil: 'networkidle' })
  const hasSummary = await waitFor(async () => (await page.locator('.summary .pair-trigger').count()) > 0, 8000)
  if (hasSummary) {
    const readPair = async () => [...(await page.locator('.pair-trigger').innerText()).matchAll(/#(\w+)/g)].map((m) => m[1])
    const [a, b] = await readPair()
    const totalBefore = (await api('/api/comparisons')).total
    await page.locator('.swap-btn').click(); await sleep(500)
    const [a2, b2] = await readPair()
    check('换向后基线/对比对调', a2 === b && b2 === a, `${a}/${b} -> ${a2}/${b2}`)
    const totalAfter = (await api('/api/comparisons')).total
    check('换向不新增历史记录', totalBefore === totalAfter, `total ${totalBefore} -> ${totalAfter}`)
  } else {
    check('对比结果页加载出对比对', false, '未出现 .pair-trigger(可能暂无对比记录)')
  }

  // ---- T5 筛选:范围 / 指定日期 模式切换 ----
  console.log('\n[T5] 筛选模式切换')
  await page.goto(`${base}/batches`, { waitUntil: 'networkidle' })
  await sleep(300)
  await page.getByText('指定日期', { exact: true }).click(); await sleep(300)
  check('切到「指定日期」出现添加按钮', (await page.getByText('添加日期', { exact: true }).count()) > 0)
  await page.getByText('范围', { exact: true }).click(); await sleep(300)
  check('切回「范围」隐藏添加按钮', (await page.getByText('添加日期', { exact: true }).count()) === 0)

  // ---- T6 切场景保留所选(像折叠状态一样;须用 SPA 切换,整页刷新会清内存态) ----
  console.log('\n[T6] 切场景保留所选批次(SPA 切换)')
  const spaPick = async (name) => {
    const sel = page.locator('.field', { hasText: '场景ID' }).locator('.arco-select')
    await sel.click(); await sleep(300)
    const opt = page.locator('.arco-select-option').filter({ hasText: name }).first()
    await opt.scrollIntoViewIfNeeded().catch(() => {})
    await opt.click({ force: true })
    await sleep(900)
  }
  await page.goto(`${base}/batches/${encodeURIComponent(scene)}`, { waitUntil: 'networkidle' })
  await sleep(400)
  await page.locator('.role-btn').nth(0).click()
  await page.locator('.role-btn').nth(1).click()
  await sleep(300)
  check('场景A:已选(VS 卡片在)', (await page.locator('.heat-cmp').count()) === 1)
  const sceneB = scenes[1]?.scene
  if (sceneB) {
    await spaPick(sceneB)
    check('切到场景B:不显示A的选择', (await page.locator('.heat-cmp').count()) === 0 && (await page.locator('.role-btn.on').count()) === 0)
    await spaPick(scene)
    check('切回场景A:选择被恢复', (await page.locator('.heat-cmp').count()) === 1)
  } else {
    check('切场景保留所选', true, '只有一个可用场景,跳过(非失败)')
  }
} catch (e) {
  check('运行未中断', false, e.message)
} finally {
  await browser.close()
}

const failed = results.filter((r) => !r.ok)
console.log(`\n=== E2E 汇总: ${results.length - failed.length}/${results.length} 通过 ；pageerror=${pageErrors.length} ===`)
if (pageErrors.length) pageErrors.slice(0, 10).forEach((e) => console.log('  pageerror:', e.slice(0, 160)))
if (failed.length) { failed.forEach((r) => console.log('  FAIL:', r.name, r.detail)); process.exit(1) }
process.exit(pageErrors.length ? 1 : 0)
