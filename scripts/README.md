# scripts/ — 测试/压测脚本(Playwright)

这些脚本对**正在运行**的应用跑(需后端 8000 + 前端 5173 在跑),用全局 Playwright
(`C:/WorkSpace/jm/node_modules/playwright`)。它们只读访问、不改库,直接用当前数据。

> 后端的功能/并发单测在 `backend/tests/`(`pytest`),与这里无关。

## e2e/run-all.mjs — 前端交互 E2E

真正点按、验证交互结果(动态发现含 ≥2 批次的场景,不依赖固定 ID):

```powershell
node scripts/e2e/run-all.mjs                       # 默认 http://localhost:5173
node scripts/e2e/run-all.mjs http://localhost:8000 # 跑打包产物
```

覆盖:列表图角色选择/高亮/取消、差异列「发起对比」就地计算且不跳转、拖拽平移(表头不可拖/图片可拖)、
单击放大 + 方向键(含切到差异热力图)、对比结果页一键换向(对调且历史不增)、筛选范围/指定日期切换、
切场景保留所选批次(SPA)。全过退出码 0;有失败或 pageerror 退出码 1。

## ui-load-smoke.mjs — 多人并发界面冒烟

开 N 个浏览器上下文模拟多人同时浏览(批次列表 → 列表图 → 对比结果),收集 console/page 报错与各页加载耗时:

```powershell
node scripts/ui-load-smoke.mjs http://localhost:5173 <场景ID> 6
```

判定:0 报错、所有页面可加载;打印各页 p50/p95/max。
