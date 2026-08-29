<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { runPageRefresh } from '../pageActions'
import GpmConfigurationTransfer from './GpmConfigurationTransfer.vue'
import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'
import { useScreenshotComparisonStore } from '../stores/screenshotComparisonStore'
import {
  batchManagementLocation,
  gpmSettingsLocation,
  primaryWorkspaces,
  safeReturnTo,
  screenshotSettingsLocation,
  workspaceContext,
} from '../workspaceNavigation'

const project = useProjectStore()
const catalog = useBatchCatalogStore()
const screenshot = useScreenshotComparisonStore()
const route = useRoute()
const router = useRouter()

const tabs = primaryWorkspaces
const context = computed(() => workspaceContext(route))
const showRefresh = computed(() => context.value.isDataPage || context.value.isManagement)
const showWorkspaceReturn = computed(() => context.value.isManagement || context.value.isSettings)
const workspaceLabel = computed(() => ({
  screenshot: '截图对比', mapBuild: '烘培数据', gpm: '热力图',
})[context.value.workspace])
// 现有手动上报弹窗只处理截图/烘培批次，且只放在对应工作区。
const showManualUpload = computed(() => (
  context.value.isDataPage && context.value.workspace !== 'gpm'
))
const showBatchManagement = computed(() => context.value.isDataPage)
const showScreenshotSettings = computed(() => (
  context.value.isDataPage && context.value.workspace === 'screenshot'
))
const showGpmSettings = computed(() => (
  context.value.isDataPage && context.value.workspace === 'gpm'
))
const showGpmConfigurationTransfer = computed(() => (
  context.value.isSettings && context.value.workspace === 'gpm'
))
const supportsAutoRefresh = computed(() => (
  showRefresh.value && context.value.workspace !== 'gpm'
))

function currentBranch() {
  const raw = route.query.branch_tag
  if (Array.isArray(raw)) return raw[0] || 'main'
  if (raw) return raw
  if (context.value.isManagement && context.value.batchDomain === 'capture') {
    return catalog.filters.branch_tag || 'main'
  }
  if (!context.value.isDataPage) {
    const source = router.resolve(context.value.returnTo)
    const sourceBranch = Array.isArray(source.query.branch_tag)
      ? source.query.branch_tag[0]
      : source.query.branch_tag
    if (sourceBranch) return sourceBranch
  }
  return 'main'
}

function tabTarget(tab) {
  if (!context.value.isDataPage && tab.id === context.value.workspace) {
    return safeReturnTo(route.query.return_to, tab.path)
  }
  let path = tab.path
  const preservesScene = context.value.isDataPage
    && context.value.workspace !== 'gpm'
    && tab.id !== 'gpm'
  if (preservesScene) {
    const rawSceneId = route.params.sceneId
    const sceneId = Array.isArray(rawSceneId) ? rawSceneId[0] : rawSceneId
    if (sceneId) path = `${tab.path}/${encodeURIComponent(sceneId)}`
  }
  return { path, query: { branch_tag: currentBranch() } }
}

function openBatchManagement() {
  return router.push(batchManagementLocation(route))
}

function openScreenshotSettings() {
  return router.push(screenshotSettingsLocation(route))
}

function openGpmSettings() {
  return router.push(gpmSettingsLocation(route))
}

function returnToWorkspace() {
  return router.push(context.value.returnTo)
}

// 按当前视图刷新对应数据;silent=true 时不弹提示(供定时自动刷新复用)
async function doRefresh({ silent = false } = {}) {
  // GPMHeatmap 使用独立数据库与筛选元数据；刷新它时不应先依赖截图批次接口。
  if (context.value.workspace !== 'gpm') await project.loadMeta()
  const handled = await runPageRefresh({ silent })
  if (!handled) return
  if (!silent) Message.success('已刷新')
}

function refresh() {
  return doRefresh().catch((error) => Message.error(error?.message || '刷新失败，请重试'))
}   // 顶栏按钮:有提示

// 定时自动刷新:固定 2 分钟一次,静默;按多重守卫跳过本轮(下一轮再判断)
const AUTO_REFRESH_MS = 120000
let autoTimer = null

function autoTick() {
  if (document.hidden) return                       // 后台标签页不刷,省请求
  if (!supportsAutoRefresh.value) return             // 热力图仅手动刷新，其他数据页自动刷
  if (project.uploadVisible || screenshot.running) return  // 上传弹窗 / 对比中,不打断
  // 截图网格也刷新:渲染 key 稳定(列=批次id、行=检查点名),Vue 复用 DOM,
  // 已有图片不重载、滚动位置不丢;有新批次时仅在末尾插入新列。
  doRefresh({ silent: true }).catch(() => {})       // 异常不应中断定时器
}

onMounted(() => {
  autoTimer = setInterval(autoTick, AUTO_REFRESH_MS)
  // 切回前台(标签重新可见)立即刷一次,不必等下一拍;切走时 autoTick 内部守卫自会跳过
  document.addEventListener('visibilitychange', autoTick)
})
onUnmounted(() => {
  if (autoTimer) clearInterval(autoTimer)
  document.removeEventListener('visibilitychange', autoTick)
})
</script>

<template>
  <header class="topbar">
    <div class="logo">
      <!-- 两帧叠加 + 差异点:像素对比的意象 -->
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="2.5" y="2.5" width="13" height="13" rx="3.5" fill="rgb(var(--arcoblue-6))" />
        <rect x="8.5" y="8.5" width="13" height="13" rx="3.5" fill="none"
          stroke="rgb(var(--arcoblue-5))" stroke-width="2" />
        <circle cx="18.5" cy="5.5" r="3" fill="rgb(var(--red-5))" />
      </svg>
      PixelComparison
    </div>
    <nav class="tabs">
      <button v-for="t in tabs" :key="t.path" class="tab"
        :class="{ active: context.workspace === t.id }"
        @click="router.push(tabTarget(t))">{{ t.label }}</button>
    </nav>
    <div class="actions">
      <a-tooltip v-if="showWorkspaceReturn" :content="`返回${workspaceLabel}`">
        <button class="icon-btn return-button" :aria-label="`返回${workspaceLabel}`"
          @click="returnToWorkspace">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 12H5" /><path d="m12 19-7-7 7-7" />
          </svg>
          <span>返回{{ workspaceLabel }}</span>
        </button>
      </a-tooltip>
      <span v-if="showWorkspaceReturn" class="action-divider" aria-hidden="true"></span>
      <GpmConfigurationTransfer v-if="showGpmConfigurationTransfer" />
      <template v-if="showRefresh">
        <a-tooltip content="刷新">
          <button class="icon-btn" aria-label="刷新" @click="refresh">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
            </svg>
          </button>
        </a-tooltip>
        <a-tooltip v-if="showManualUpload" content="手动上报">
          <button class="icon-btn" aria-label="手动上报" @click="project.uploadVisible = true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M5 20h14" />
            </svg>
          </button>
        </a-tooltip>
      </template>
      <a-tooltip v-if="showBatchManagement" content="批次管理">
        <button class="icon-btn" aria-label="批次管理" @click="openBatchManagement">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="7" ry="3" />
            <path d="M5 5v6c0 1.66 3.13 3 7 3s7-1.34 7-3V5" />
            <path d="M5 11v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" />
          </svg>
        </button>
      </a-tooltip>
      <a-tooltip v-if="showScreenshotSettings" content="截图对比设置">
        <button class="icon-btn" aria-label="截图对比设置" @click="openScreenshotSettings">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.14.37.35.7.6 1 .3.28.68.42 1.1.4H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.6z" />
          </svg>
        </button>
      </a-tooltip>
      <a-tooltip v-if="showGpmSettings" content="热力图设置">
        <button class="icon-btn" aria-label="热力图设置" @click="openGpmSettings">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.14.37.35.7.6 1 .3.28.68.42 1.1.4H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.6z" />
          </svg>
        </button>
      </a-tooltip>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: 52px; flex: 0 0 52px; display: flex; align-items: center; gap: 24px;
  padding: 0 20px; background: var(--color-bg-2);
  border-bottom: 1px solid var(--color-border-1);
}
.logo { font-size: 16px; font-weight: 700; display: flex; align-items: center; gap: 9px; letter-spacing: .2px; }
.tabs { display: flex; gap: 8px; height: 100%; }
.tab {
  border: none; background: none; padding: 0 16px; font-size: 14px; cursor: pointer;
  color: var(--color-text-2); position: relative; font-family: inherit;
}
.tab:hover { color: var(--color-text-1); }
.tab.active { color: rgb(var(--arcoblue-6)); font-weight: 600; }
.tab.active::after {
  content: ""; position: absolute; left: 12px; right: 12px; bottom: 0;
  height: 2px; background: rgb(var(--arcoblue-6)); border-radius: 2px;
}
.actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.action-divider { width: 1px; height: 18px; margin: 0 2px; background: var(--color-border-2); }
.icon-btn {
  width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--color-border-2); background: transparent;
  color: var(--color-text-2); display: flex; align-items: center; justify-content: center;
}
.icon-btn:hover { background: var(--color-fill-2); color: var(--color-text-1); }
.return-button {
  box-sizing: border-box; width: auto; min-width: 92px; height: 34px;
  padding: 8px 11px; gap: 6px; border-radius: 7px; line-height: 16px;
  border-color: rgba(var(--arcoblue-5), .42); color: rgb(var(--arcoblue-6));
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 8%, transparent);
  font-size: 11px; white-space: nowrap;
}
.return-button svg { flex: 0 0 auto; display: block; }
.return-button span { line-height: 16px; }
.return-button:hover {
  border-color: rgba(var(--arcoblue-5), .7);
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 14%, var(--color-fill-2));
}
.icon-btn.active {
  border-color: rgb(var(--arcoblue-5));
  background: var(--color-primary-light-1);
  color: rgb(var(--arcoblue-6));
}
</style>
