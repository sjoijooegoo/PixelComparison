<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BatchGrid from '../components/BatchGrid.vue'
import ScreenshotFilters from '../components/ScreenshotFilters.vue'
import { registerPageRefresh } from '../pageActions'
import {
  parseScreenshotRoute,
  screenshotLocation,
  screenshotRouteKey,
  screenshotStateFromFilters,
} from '../screenshotRoute'
import { useProjectStore } from '../stores/projectStore'
import { useScreenshotComparisonStore } from '../stores/screenshotComparisonStore'

defineOptions({ name: 'ScreenshotComparisonView' })

const project = useProjectStore()
const store = useScreenshotComparisonStore()
const route = useRoute()
const router = useRouter()
let writingUrl = false
let unregisterPageRefresh = null
let routeRun = 0
let initialActivation = true
let synchronizedRouteKey = ''
let pageActive = false
const routeError = ref('')

const selectedSceneHasScreenshots = computed(() => (
  project.meta.scene_data_flags?.[store.filters.branch_tag]?.[store.filters.scene_id]
    ?.has_screenshots === true
))

const routeState = () => parseScreenshotRoute(route)

async function replaceUrl(state) {
  synchronizedRouteKey = screenshotRouteKey(state)
  const target = screenshotLocation(state)
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
  routeError.value = ''
  try {
    await project.init()
    if (run !== routeRun || !pageActive) return
    const normalized = await store.applyRoute(routeState())
    if (run !== routeRun || !pageActive || !normalized) return
    synchronizedRouteKey = screenshotRouteKey(normalized)
    await replaceUrl(normalized)
  } catch (error) {
    if (run === routeRun && pageActive && !error?.cancelled) {
      routeError.value = error?.message || '截图对比加载失败'
    }
  }
}

async function syncRoleUrl() {
  if (!store.initialized || writingUrl || !route.path.startsWith('/screenshot')) return
  await replaceUrl(screenshotStateFromFilters(store.filters, {
    baselineId: store.baselineBatch ? String(store.baselineBatch.id) : '',
    currentId: store.currentBatch ? String(store.currentBatch.id) : '',
  }))
}

function registerRefresh() {
  unregisterPageRefresh?.()
  unregisterPageRefresh = registerPageRefresh(async () => {
    await store.refresh()
  })
}

watch(() => route.fullPath, () => {
  if (writingUrl || !route.path.startsWith('/screenshot')) return
  const requested = routeState()
  // Select 的 v-model 会在 router.push 前先改 store，因此不能用 store 值
  // 判断路由是否已处理。只有由本页成功加载或同步过的 URL 才可跳过。
  if (store.initialized && screenshotRouteKey(requested) === synchronizedRouteKey) return
  void applyRoute()
})
watch(
  () => [store.baselineBatch?.id, store.currentBatch?.id],
  () => { void syncRoleUrl() },
)

onMounted(() => {
  pageActive = true
  registerRefresh()
  void applyRoute()
})
onActivated(() => {
  pageActive = true
  if (initialActivation) {
    initialActivation = false
    return
  }
  registerRefresh()
  if (!route.path.startsWith('/screenshot')) return
  const requested = routeState()
  if (store.initialized && screenshotRouteKey(requested) === synchronizedRouteKey) {
    void store.loadGridHeatmaps()
  }
  else void applyRoute()
})
onDeactivated(() => {
  pageActive = false
  routeRun += 1
  unregisterPageRefresh?.()
  unregisterPageRefresh = null
  store.deactivate()
})
onUnmounted(() => {
  pageActive = false
  routeRun += 1
  unregisterPageRefresh?.()
  store.deactivate()
})
</script>

<template>
  <div class="app-body app-body--col">
    <ScreenshotFilters />
    <main class="app-main">
      <section class="screenshot-panel">
        <div v-if="routeError" class="workspace-empty workspace-error">
          <span>{{ routeError }}</span>
          <a-button type="primary" size="small" @click="applyRoute">重新加载</a-button>
        </div>
        <div v-else-if="!store.filters.scene_id" class="workspace-empty">
          请选择一个包含截图数据的场景
        </div>
        <div v-else-if="!store.initialized" class="workspace-empty">
          <a-spin :size="28" tip="正在恢复截图对比…" />
        </div>
        <div v-else-if="!store.gridLoading && !store.gridError && !store.grid.batches.length"
          class="workspace-empty">
          {{ selectedSceneHasScreenshots
            ? '当前筛选条件下没有包含截图的批次'
            : '当前分支和场景下没有包含截图的批次' }}
        </div>
        <BatchGrid v-else />
      </section>
    </main>
  </div>
</template>

<style scoped>
.app-body--col { flex-direction: column; }
.screenshot-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.workspace-empty { flex: 1; display: grid; place-items: center; color: var(--color-text-3); font-size: 13px; }
.workspace-error { align-content: center; gap: 10px; color: rgb(var(--red-6)); }
</style>
