<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  batchLocation,
  batchRouteKey,
  parseBatchRoute,
} from '../batchRoute'
import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'
import FilterSidebar from '../components/FilterSidebar.vue'
import BatchTable from '../components/BatchTable.vue'
import { registerPageRefresh } from '../pageActions'

defineOptions({ name: 'BatchView' })

const project = useProjectStore()
const store = useBatchCatalogStore()
const route = useRoute()
const router = useRouter()
let unregisterPageRefresh = null
let pageActive = false
let writingUrl = false
let routeRun = 0
let synchronizedRouteKey = ''

const routeState = () => parseBatchRoute(route)

async function replaceUrl(state) {
  synchronizedRouteKey = batchRouteKey(state)
  const target = batchLocation(state)
  if (route.fullPath === router.resolve(target).fullPath) return
  writingUrl = true
  try {
    await router.replace(target)
  } finally {
    writingUrl = false
  }
}

async function applyRoute() {
  if (!pageActive) return
  const run = ++routeRun
  try {
    await project.init()
    if (run !== routeRun || !pageActive) return
    const normalized = await store.applyRoute(routeState())
    if (run !== routeRun || !pageActive || !normalized) return
    normalized.returnTo = routeState().returnTo
    synchronizedRouteKey = batchRouteKey(normalized)
    await replaceUrl(normalized)
  } catch {
    // 项目或批次错误状态由对应 Store 保留，页面提供原位重试。
  }
}

function registerRefresh() {
  unregisterPageRefresh?.()
  unregisterPageRefresh = registerPageRefresh(async () => {
    await store.refresh({ refreshMeta: false })
  })
}

watch(() => route.fullPath, () => {
  if (writingUrl || route.path !== '/batch-management/capture') return
  const requested = routeState()
  if (store.initialized && batchRouteKey(requested) === synchronizedRouteKey) return
  void applyRoute()
})

onMounted(() => {
  pageActive = true
  registerRefresh()
  void applyRoute()
})
onUnmounted(() => {
  pageActive = false
  routeRun += 1
  unregisterPageRefresh?.()
  store.deactivate()
})
</script>

<template>
  <!-- 批次管理:筛选条(上方横排) + 批次列表 -->
  <div class="app-body app-body--col">
    <div v-if="project.initializing || (!store.initialized && store.batchLoading)" class="startup-state card">
      <a-spin :size="32" tip="正在加载项目配置和批次数据…" />
    </div>
    <div v-else-if="project.initError" class="startup-state card">
      <div class="startup-title">页面加载失败</div>
      <div class="startup-message">{{ project.initError }}</div>
      <a-button type="primary" size="small" @click="applyRoute">重新加载</a-button>
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
