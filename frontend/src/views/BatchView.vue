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

// URL → 状态:带场景参数则以列表图展示该场景(日期沿用默认近七天)
function applyRoute() {
  const sid = route.params.sceneId
  if (!sid) return                       // 无参数:保持当前状态(默认列表)
  store.batchView = 'grid'
  if (store.filters.scene_id !== sid) {
    store.filters.scene_id = sid
    store.batchPage = 1
    store.loadBatches()
    store.loadGrid()
  } else if (!store.grid.batches.length) {
    store.loadGrid()                      // 同场景已有数据则不重复拉取/重渲染
  }
}
onMounted(applyRoute)
watch(() => route.params.sceneId, applyRoute)

// 状态 → URL:在列表图且选了场景时,把场景写进地址栏(可直接复制分享)
watch(
  () => [store.batchView, store.filters.scene_id],
  () => {
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
