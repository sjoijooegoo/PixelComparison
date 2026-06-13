<script setup>
import { onMounted, ref } from 'vue'
import { useStore } from './store'
import TopBar from './components/TopBar.vue'
import FilterSidebar from './components/FilterSidebar.vue'
import BatchTable from './components/BatchTable.vue'
import SceneList from './components/SceneList.vue'
import DetailView from './components/DetailView.vue'
import MetricsPanel from './components/MetricsPanel.vue'

const store = useStore()
const activeTab = ref('batch')

onMounted(() => store.init())
</script>

<template>
  <div class="app-layout">
    <TopBar v-model:active="activeTab" />

    <div v-if="activeTab === 'batch'" class="app-body">
      <FilterSidebar />
      <main class="app-main">
        <BatchTable />
        <div v-if="store.selectedComparison" class="lower">
          <SceneList />
          <div class="detail-wrap card">
            <DetailView />
            <MetricsPanel />
          </div>
        </div>
        <div v-else class="lower-empty card">
          <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2.5" y="3" width="12" height="12" rx="2" />
            <rect x="9.5" y="9" width="12" height="12" rx="2" />
          </svg>
          <div class="empty-title">选择「对比批次」与「基线批次」后发起对比</div>
          <div class="empty-sub">在上方批次列表中各选一行,点击「发起对比」查看场景差异</div>
        </div>
      </main>
    </div>

    <a-result v-else status="info" :title="'「' + activeTab + '」页面为演示占位'"
      style="margin-top: 120px">
      <template #subtitle>点击「批次管理」返回主界面</template>
    </a-result>
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
