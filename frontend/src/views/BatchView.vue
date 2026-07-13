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
  const wasGrid = store.batchView === 'grid'
  const sceneChanged = store.filters.scene_id !== sid
  store.batchView = 'grid'
  if (sceneChanged) {
    store.filters.scene_id = sid
    store.batchPage = 1
    await Promise.all([store.loadBatches(), store.loadGrid()])
  } else if (!store.initialized) {
    await store.init(sid)                 // bootstrap 失败后的完整兜底重试
  } else if (!wasGrid) {
    await store.loadGrid()                // 同场景从列表切到列表图时只补矩阵
  }
}
onMounted(applyRoute)
watch(() => route.params.sceneId, applyRoute)

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
    <FilterSidebar />
    <main class="app-main">
      <BatchTable />
    </main>
  </div>
</template>

<style scoped>
/* 批次页:筛选条在上、列表在下(纵向堆叠) */
.app-body--col { flex-direction: column; }
</style>
