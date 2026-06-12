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
        <div class="lower">
          <SceneList />
          <DetailView />
          <MetricsPanel />
        </div>
      </main>
    </div>

    <a-result v-else status="info" :title="'「' + activeTab + '」页面为演示占位'"
      style="margin-top: 120px">
      <template #subtitle>点击「批次管理」返回主界面</template>
    </a-result>
  </div>
</template>
