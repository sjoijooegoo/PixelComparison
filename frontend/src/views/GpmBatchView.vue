<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
let routeSequence = 0
let synchronizedKey = ''
let unregisterRefresh = null

async function applyRoute() {
  if (!active) return
  const sequence = ++routeSequence
  const requested = parseGpmBatchRoute(route)
  try {
    const normalized = await store.applyRoute(requested)
    if (!active || sequence !== routeSequence) return
    synchronizedKey = gpmBatchRouteKey(normalized)
    const target = gpmBatchLocation(normalized)
    if (route.fullPath !== router.resolve(target).fullPath) {
      writingUrl = true
      try { await router.replace(target) } finally { writingUrl = false }
    }
  } catch {
    // Store 保留可重试错误态。
  }
}

watch(() => route.fullPath, () => {
  if (writingUrl || route.path !== '/batch-management/gpm') return
  const requested = parseGpmBatchRoute(route)
  if (store.initialized && gpmBatchRouteKey(requested) === synchronizedKey) return
  void applyRoute()
})

onMounted(() => {
  active = true
  unregisterRefresh = registerPageRefresh(() => store.refresh())
  void applyRoute()
})
onUnmounted(() => {
  active = false
  routeSequence += 1
  unregisterRefresh?.()
  store.deactivate()
})
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
