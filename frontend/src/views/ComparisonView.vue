<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from '../store'
import ResultSummary from '../components/ResultSummary.vue'
import SceneList from '../components/SceneList.vue'
import DetailView from '../components/DetailView.vue'
import MetricsPanel from '../components/MetricsPanel.vue'

const store = useStore()
const route = useRoute()
const router = useRouter()
let routeSyncSequence = 0

function isLatestRouteSync(sequence) {
  return sequence === routeSyncSequence
}

async function replaceSelectedRoute(sequence) {
  if (!isLatestRouteSync(sequence)) return
  const comparisonId = store.selectedComparison?.id
  await router.replace({
    path: comparisonId ? `/comparison/${comparisonId}` : '/comparison',
    query: { branch_tag: store.filters.branch_tag },
  })
}

// 路由驱动:带 id 则打开该对比(深链/列头跳转,方向由 ?flip 还原),否则默认打开最近一条
async function sync() {
  const sequence = ++routeSyncSequence
  const rawBranch = route.query.branch_tag
  const branchTag = String(Array.isArray(rawBranch) ? rawBranch[0] : rawBranch || 'main')
    .trim().toLowerCase()
  const routePath = route.path
  const routeQuery = { ...route.query }
  const id = route.params.id
  const flip = route.query.flip === '1'
  if (store.filters.branch_tag !== branchTag) {
    await store.changeComparisonBranch(branchTag)
    if (!isLatestRouteSync(sequence)) return
    if (store.filters.branch_tag !== branchTag) {
      await router.replace({
        path: routePath,
        query: { ...routeQuery, branch_tag: store.filters.branch_tag },
      })
      return
    }
  }
  if (id) {
    // openComparisonById 在历史已加载时直接命中,缺失才补拉一次,避免每次切换都重复请求
    const ok = await store.openComparisonById(id, flip)
    if (!isLatestRouteSync(sequence)) return
    if (!ok) {
      if (store.comparisons.length) await store.openComparison(store.comparisons[0])
      if (!isLatestRouteSync(sequence)) return
      await replaceSelectedRoute(sequence)
    }
  } else {
    if (!store.comparisons.length) await store.loadComparisons()
    if (!isLatestRouteSync(sequence)) return
    if (!store.selectedComparison && store.comparisons.length) {
      await store.openComparison(store.comparisons[0])
    } else {
      await store.resumeComparisonData()
    }
  }
}

async function onBranchChange(branchTag) {
  const sequence = ++routeSyncSequence
  await store.changeComparisonBranch(branchTag)
  if (!isLatestRouteSync(sequence)) return
  await replaceSelectedRoute(sequence)
}

async function onFilterChange() {
  const sequence = ++routeSyncSequence
  await store.applyComparisonFilters()
  if (!isLatestRouteSync(sequence)) return
  await replaceSelectedRoute(sequence)
}
onMounted(sync)
onUnmounted(() => {
  routeSyncSequence += 1
  store.cancelComparisonDataRequests()
})
watch(() => route.params.id, sync)   // 同组件内仅 id 变化(如从一条跳另一条)也重新加载
watch(() => route.query.branch_tag, sync)
</script>

<template>
  <!-- 对比结果:摘要栏(内含历史切换) + 场景列表 + 详情 + 指标 -->
  <div class="app-body">
    <main class="app-main">
      <div class="comparison-filter card">
        <div class="filter-field">
          <span class="filter-label">分支</span>
          <a-select v-model="store.filters.branch_tag" size="small" style="width: 180px"
            @change="onBranchChange">
            <a-option v-for="branch in store.meta.branch_tags" :key="branch" :value="branch">
              {{ branch }}
            </a-option>
          </a-select>
        </div>
        <div class="filter-field">
          <span class="filter-label">场景ID</span>
          <a-select v-model="store.comparisonFilters.scene_id" allow-clear allow-search
            placeholder="全部场景" size="small" style="width: 280px" @change="onFilterChange">
            <a-option v-for="sceneId in store.meta.scene_ids" :key="sceneId" :value="sceneId">
              {{ sceneId }}
            </a-option>
          </a-select>
        </div>
        <div class="filter-field">
          <span class="filter-label">状态</span>
          <a-select v-model="store.comparisonFilters.status" allow-clear placeholder="全部状态"
            size="small" style="width: 130px" @change="onFilterChange">
            <a-option value="fail">失败</a-option>
            <a-option value="warn">警告</a-option>
            <a-option value="pass">通过</a-option>
          </a-select>
        </div>
      </div>
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
          @click="router.push({ path: '/batches', query: { branch_tag: store.filters.branch_tag } })">前往批次管理</a-button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.comparison-filter {
  flex: 0 0 auto; display: flex; align-items: center; gap: 8px; padding: 10px 14px;
}
.filter-field { display: flex; align-items: center; gap: 6px; }
.filter-label { color: var(--color-text-3); font-size: 12px; }
.lower-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; color: var(--color-text-3);
}
.lower-empty svg { color: var(--color-text-4); margin-bottom: 4px; }
.empty-title { font-size: 14px; color: var(--color-text-2); }
.empty-sub { font-size: 12px; color: var(--color-text-4); }
</style>
