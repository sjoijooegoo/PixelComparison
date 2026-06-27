<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { theme, toggleTheme } from '../theme'
import { useStore } from '../store'

const store = useStore()
const route = useRoute()
const router = useRouter()

const tabs = [
  { path: '/batches', label: '批次管理' },
  { path: '/comparison', label: '对比结果' },
  { path: '/settings', label: '项目设置' },
]

// 当前路径(根路径视作批次管理)
const current = computed(() => (route.path === '/' ? '/batches' : route.path))
// 前缀匹配:/batches/<场景> 时「批次管理」仍高亮
const isActive = (path) => current.value === path || current.value.startsWith(path + '/')
const showBatchActions = computed(() => isActive('/batches') || isActive('/comparison'))

// 按当前视图刷新对应数据;silent=true 时不弹提示(供定时自动刷新复用)
async function doRefresh({ silent = false } = {}) {
  if (isActive('/comparison')) {
    await store.loadComparisons()
  } else {
    await store.refreshBatches()
  }
  if (!silent) Message.success('已刷新')
}

function refresh() { return doRefresh() }   // 顶栏按钮:有提示

// 定时自动刷新:固定 1 分钟一次,静默;按多重守卫跳过本轮(下一轮再判断)
const AUTO_REFRESH_MS = 60000
let autoTimer = null

function autoTick() {
  if (document.hidden) return                       // 后台标签页不刷,省请求
  if (!showBatchActions.value) return               // 仅批次/对比页(设置页不刷)
  if (store.uploadVisible || store.running) return  // 上传弹窗 / 对比中,不打断
  // 列表图也刷新:渲染 key 稳定(列=批次id、行=检查点名),Vue 复用 DOM,
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
        :class="{ active: isActive(t.path) }"
        @click="router.push(t.path)">{{ t.label }}</button>
    </nav>
    <div class="actions">
      <template v-if="showBatchActions">
        <a-tooltip content="刷新">
          <button class="icon-btn" @click="refresh">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
            </svg>
          </button>
        </a-tooltip>
        <a-tooltip content="手动上报">
          <button class="icon-btn" @click="store.uploadVisible = true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M5 20h14" />
            </svg>
          </button>
        </a-tooltip>
      </template>
      <a-tooltip :content="theme === 'dark' ? '切换亮色' : '切换暗色'">
        <button class="icon-btn" @click="toggleTheme">
          <svg v-if="theme === 'dark'" width="15" height="15" viewBox="0 0 16 16" fill="none"
            stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <circle cx="8" cy="8" r="3.2" />
            <path d="M8 1.2v1.8M8 13v1.8M1.2 8H3M13 8h1.8M3.2 3.2l1.3 1.3M11.5 11.5l1.3 1.3M12.8 3.2l-1.3 1.3M4.5 11.5l-1.3 1.3" />
          </svg>
          <svg v-else width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
            <path d="M13.8 9.7A6 6 0 0 1 6.3 2.2a6 6 0 1 0 7.5 7.5z" />
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
.icon-btn {
  width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--color-border-2); background: transparent;
  color: var(--color-text-2); display: flex; align-items: center; justify-content: center;
}
.icon-btn:hover { background: var(--color-fill-2); color: var(--color-text-1); }
</style>
