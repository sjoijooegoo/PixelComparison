<script setup>
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from '../store'
import FilterSidebar from '../components/FilterSidebar.vue'
import BatchTable from '../components/BatchTable.vue'

defineOptions({ name: 'BatchView' })   // 供 <keep-alive include> 命中

const store = useStore()
const route = useRoute()
const router = useRouter()

// URL → 状态:带场景参数则以列表图展示该场景。
// 首屏数据已由 main.js 在挂载前加载；这里只处理后续路由切换，或初始化失败后的兜底。
async function applyRoute() {
  const rawSid = route.params.sceneId
  const sid = Array.isArray(rawSid) ? rawSid[0] : rawSid
  if (!sid) return                       // 无参数:保持当前状态(默认列表)
  if (!store.initialized) {
    try {
      await store.init(sid)               // 与 bootstrap 共用同一轮 Promise，不重复发请求
    } catch {
      return                              // 错误由页面状态展示，避免事件处理器产生未处理拒绝
    }
    const latest = route.params.sceneId
    const latestSid = Array.isArray(latest) ? latest[0] : latest
    if (latestSid !== sid) return          // 初始化期间路由已变化，由最新一轮 applyRoute 接管
  }
  if (!store.meta.scene_ids.includes(sid)) {
    const needsReload = store.filters.scene_id || store.batchView !== 'list'
    store.filters.scene_id = ''
    store.batchView = 'list'
    store.batchPage = 1
    if (needsReload) await store.refreshBatches()
    if (route.path !== '/batches') await router.replace('/batches')
    return
  }
  const wasGrid = store.batchView === 'grid'
  const sceneChanged = store.filters.scene_id !== sid
  store.batchView = 'grid'
  if (sceneChanged) {
    store.filters.scene_id = sid
    store.batchPage = 1
    await Promise.all([store.loadBatches(), store.loadGrid()])
  } else if (!wasGrid) {
    await store.loadGrid()                // 同场景从列表切到列表图时只补矩阵
  }
}
onMounted(applyRoute)
watch(() => route.params.sceneId, applyRoute)

async function retryInit() {
  const rawSid = route.params.sceneId
  const sid = Array.isArray(rawSid) ? rawSid[0] : rawSid
  try {
    await store.init(sid || '')
  } catch {
    // initError 已更新，保留错误卡片供继续重试。
  }
}

// 状态 → URL:在列表图且选了场景时,把场景写进地址栏(可直接复制分享)。
// 依赖里带上 route.path:从对比结果切回 /batches(顶栏 push 不带场景)时也能把
// 场景段补回。startsWith 守卫确保只在批次页内同步,不会在 /comparison 等页把用户拽回来。
watch(
  () => [store.batchView, store.filters.scene_id, route.path],
  () => {
    if (!route.path.startsWith('/batches')) return
    const want = (store.batchView === 'grid' && store.filters.scene_id)
      ? `/batches/${encodeURIComponent(store.filters.scene_id)}`
      : '/batches'
    if (route.path !== want) router.replace(want)
  },
)
</script>

<template>
  <!-- 批次管理:筛选条(上方横排) + 批次列表 -->
  <div class="app-body app-body--col">
    <div v-if="store.initializing" class="startup-state card">
      <a-spin :size="32" tip="正在加载项目配置和批次数据…" />
    </div>
    <div v-else-if="store.initError" class="startup-state card">
      <div class="startup-title">页面加载失败</div>
      <div class="startup-message">{{ store.initError }}</div>
      <a-button type="primary" size="small" @click="retryInit">重新加载</a-button>
    </div>
    <template v-else>
      <FilterSidebar />
      <main class="app-main">
        <BatchTable />
      </main>
    </template>
  </div>
</template>

<style scoped>
/* 批次页:筛选条在上、列表在下(纵向堆叠) */
.app-body--col { flex-direction: column; }
.startup-state {
  flex: 1; min-height: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
}
.startup-title { color: var(--color-text-1); font-size: 15px; font-weight: 600; }
.startup-message { max-width: 560px; color: var(--color-text-3); font-size: 12px; text-align: center; }
</style>
