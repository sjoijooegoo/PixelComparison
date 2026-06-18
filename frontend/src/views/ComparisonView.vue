<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from '../store'
import ResultSummary from '../components/ResultSummary.vue'
import SceneList from '../components/SceneList.vue'
import DetailView from '../components/DetailView.vue'
import MetricsPanel from '../components/MetricsPanel.vue'

const store = useStore()
const router = useRouter()

// 进入对比结果页:拉取历史,若未选中则自动打开最近一条
onMounted(async () => {
  await store.loadComparisons()
  if (!store.selectedComparison && store.comparisons.length) {
    store.openComparison(store.comparisons[0])
  }
})
</script>

<template>
  <!-- 对比结果:摘要栏(内含历史切换) + 场景列表 + 详情 + 指标 -->
  <div class="app-body">
    <main class="app-main">
      <template v-if="store.selectedComparison">
        <ResultSummary />
        <div class="lower">
          <SceneList />
          <div class="detail-wrap card">
            <DetailView />
            <MetricsPanel />
          </div>
        </div>
      </template>
      <div v-else class="lower-empty card">
        <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2.5" y="3" width="12" height="12" rx="2" />
          <rect x="9.5" y="9" width="12" height="12" rx="2" />
        </svg>
        <div class="empty-title">还没有对比结果</div>
        <div class="empty-sub">请先在「批次管理」中选择两个批次并发起对比</div>
        <a-button type="primary" size="small" style="margin-top:4px"
          @click="router.push('/batches')">前往批次管理</a-button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.lower-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; color: var(--color-text-3);
}
.lower-empty svg { color: var(--color-text-4); margin-bottom: 4px; }
.empty-title { font-size: 14px; color: var(--color-text-2); }
.empty-sub { font-size: 12px; color: var(--color-text-4); }
</style>
