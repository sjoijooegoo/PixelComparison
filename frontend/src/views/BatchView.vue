<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'
import FilterSidebar from '../components/FilterSidebar.vue'
import BatchTable from '../components/BatchTable.vue'
import { registerPageRefresh } from '../pageActions'

defineOptions({ name: 'BatchView' })

const project = useProjectStore()
const store = useBatchCatalogStore()
let unregisterPageRefresh = null
let pageActive = false

async function retryInit() {
  try {
    await project.init()
    if (!pageActive) return
    await store.init()
  } catch {
    // 错误状态保留在页面，供用户继续重试。
  }
}

onMounted(async () => {
  pageActive = true
  await retryInit()
  if (!pageActive) return
  unregisterPageRefresh = registerPageRefresh(async () => {
    await store.refresh({ refreshMeta: false })
  })
})
onUnmounted(() => {
  pageActive = false
  unregisterPageRefresh?.()
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
