<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  gpmBatchLocation,
  gpmBatchRouteKey,
  parseGpmBatchRoute,
} from '../gpmBatchRoute'
import { registerPageRefresh } from '../pageActions'
import { useGpmBatchStore } from '../stores/gpmBatchStore'
import GpmBatchFilters from '../components/GpmBatchFilters.vue'
import GpmBatchTable from '../components/GpmBatchTable.vue'

const store = useGpmBatchStore()
const route = useRoute()
const router = useRouter()
let active = false
let writingUrl = false
let applyingRoute = false
let routeSequence = 0
let synchronizedKey = ''
let unregisterRefresh = null

async function syncRoute(normalized) {
  if (!active || route.path !== '/batch-management/gpm') return
  synchronizedKey = gpmBatchRouteKey(normalized)
  const target = gpmBatchLocation(normalized)
  if (route.fullPath !== router.resolve(target).fullPath) {
    writingUrl = true
    try { await router.replace(target) } finally { writingUrl = false }
  }
}

async function applyRoute() {
  if (!active) return
  const sequence = ++routeSequence
  applyingRoute = true
  const requested = parseGpmBatchRoute(route)
  try {
    const normalized = await store.applyRoute(requested)
    if (!active || sequence !== routeSequence) return
    await syncRoute(normalized)
  } catch {
    // Store 保留可重试错误态。
  } finally {
    if (sequence === routeSequence) applyingRoute = false
  }
}

watch(() => route.fullPath, () => {
  if (writingUrl || route.path !== '/batch-management/gpm') return
  const requested = parseGpmBatchRoute(route)
  if (store.initialized && gpmBatchRouteKey(requested) === synchronizedKey) return
  void applyRoute()
})

// 每页行数随窗口变化；服务器重新定位后同步实际页码，不额外发起列表请求。
watch(() => store.loading, (loading) => {
  if (loading || !active || applyingRoute || writingUrl || !store.initialized || !synchronizedKey) return
  if (!route.query.focus_batch) return
  void syncRoute(store.routeState(route.query.return_to || '')).catch(() => {})
})

onMounted(() => {
  active = true
  unregisterRefresh = registerPageRefresh(() => store.refresh())
  void applyRoute()
})
function deactivatePage() {
  active = false
  routeSequence += 1
  unregisterRefresh?.()
  store.deactivate()
}
onBeforeRouteLeave(deactivatePage)
onUnmounted(deactivatePage)
</script>

<template>
  <main class="gpm-batch-page app-body">
    <GpmBatchFilters />
    <GpmBatchTable />
  </main>
</template>

<style scoped>
.gpm-batch-page { position: relative; flex-direction: column; }
</style>
