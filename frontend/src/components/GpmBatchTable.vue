<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useRoute, useRouter } from 'vue-router'
import { gpmBatchLocation } from '../gpmBatchRoute'
import { useGpmBatchStore } from '../stores/gpmBatchStore'
import Pager from './Pager.vue'
import { createBatchTableSizer } from './batchTableSizer'

const store = useGpmBatchStore()
const route = useRoute()
const router = useRouter()
const deletingId = ref(null)
const tableWrap = ref(null)
const tableSizer = createBatchTableSizer(store)
let mounted = false

const columns = [
  { title: '批次 ID', dataIndex: 'batch_id', slotName: 'batch', width: 150 },
  { title: '分支', dataIndex: 'branch_tag', width: 120 },
  { title: '地图', slotName: 'maps', width: 260 },
  { title: '平台', dataIndex: 'platform', slotName: 'platform', width: 100 },
  { title: '画质', dataIndex: 'shading_quality_label', slotName: 'quality', width: 90 },
  { title: 'P4 版本', dataIndex: 'p4_version', slotName: 'p4', width: 110 },
  { title: '采集时间', dataIndex: 'captured_at', slotName: 'captured', width: 170 },
  { title: '点位 / 截图', slotName: 'counts', width: 120 },
  { title: '地图配置', slotName: 'mapStatus', width: 130 },
  { title: '操作', slotName: 'ops', width: 180, align: 'center' },
]

function formatTime(value) {
  return String(value || '').replace('T', ' ').slice(0, 19) || '——'
}

function mapNamesLabel(record) {
  const mapNames = record.map_names || []
  if (!mapNames.length) return '——'
  return mapNames.length === 1 ? mapNames[0] : `${mapNames[0]} 等 ${mapNames.length} 张地图`
}

function mapLabel(record) {
  if (record.map_status === 'configured') return `${record.configured_map_count}/${record.map_count} 已配置`
  if (record.map_status === 'partial') return `${record.configured_map_count}/${record.map_count} 已配置`
  return '未配置'
}

function mapColor(record) {
  if (record.map_status === 'configured') return 'green'
  if (record.map_status === 'partial') return 'orange'
  return 'gray'
}

function openHeatmap(record) {
  const mapName = record.map_names?.[0]
  if (!mapName) return
  router.push({
    path: `/gpm-heatmap/${encodeURIComponent(mapName)}`,
    query: {
      branch_tag: record.branch_tag,
      platform: record.platform,
      quality: String(record.shading_quality),
      batch: record.batch_id,
    },
  })
}

async function remove(record) {
  deletingId.value = record.id
  try {
    await store.deleteBatch(record.batch_id, record.branch_tag)
    await router.replace(gpmBatchLocation({
      returnTo: route.query.return_to || '', ...store.filters, page: store.batchPage,
    }))
    Message.success(`已删除热力图批次 ${record.batch_id}`)
  } catch (error) {
    Message.error(error?.message || '删除失败')
  } finally {
    deletingId.value = null
  }
}

function changePage(page) {
  return router.push(gpmBatchLocation({
    returnTo: route.query.return_to || '', ...store.filters, page,
  }))
}

async function syncTableWrap() {
  await nextTick()
  if (mounted) tableSizer.observe(tableWrap.value)
}

watch(tableWrap, syncTableWrap, { flush: 'post' })
watch(() => store.batches.length, () => nextTick(() => {
  if (mounted && tableWrap.value) tableSizer.recalc()
}))
onMounted(() => { mounted = true; void syncTableWrap() })
onUnmounted(() => { mounted = false; tableSizer.disconnect() })
</script>

<template>
  <section class="gpm-batch-panel card">
    <div ref="tableWrap" class="table-wrap">
      <div v-if="store.error" class="load-error">
        <span>{{ store.error }}</span>
        <a-button size="mini" type="primary" @click="store.loadBatches().catch(() => {})">
          重新加载
        </a-button>
      </div>
      <a-table :columns="columns" :data="store.batches" :pagination="false"
        :loading="store.loading" row-key="id" size="medium">
        <template #batch="{ record }">
          <a v-if="record.batch_url" class="batch-link mono" :href="record.batch_url"
            target="_blank" rel="noopener noreferrer" title="查看流水线">
            #{{ record.batch_id }}
          </a>
          <span v-else class="mono batch-id">#{{ record.batch_id }}</span>
        </template>
        <template #maps="{ record }">
          <span class="scene-label" :title="(record.map_names || []).join('\n')">{{ mapNamesLabel(record) }}</span>
        </template>
        <template #platform="{ record }"><a-tag size="small">{{ record.platform }}</a-tag></template>
        <template #quality="{ record }"><a-tag size="small" color="arcoblue">{{ record.shading_quality_label }}</a-tag></template>
        <template #p4="{ record }"><span class="mono">{{ record.p4_version ?? '——' }}</span></template>
        <template #captured="{ record }"><span class="mono">{{ formatTime(record.captured_at) }}</span></template>
        <template #counts="{ record }">
          <span class="mono">{{ record.point_count }} / {{ record.screenshot_count }}</span>
        </template>
        <template #mapStatus="{ record }">
          <a-tag size="small" :color="mapColor(record)">{{ mapLabel(record) }}</a-tag>
        </template>
        <template #ops="{ record }">
          <a-button size="mini" type="text" @click="openHeatmap(record)">查看热力图</a-button>
          <a-popconfirm position="br" type="warning" ok-text="删除" cancel-text="取消"
            :content="`删除批次 ${record.batch_id}？将删除其全部地图数据、点位、指标和截图；独立地图配置不会删除。`"
            @ok="remove(record)">
            <a-button size="mini" type="text" class="delete-button" title="删除批次"
              :loading="deletingId === record.id">
              <template #icon>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" />
                </svg>
              </template>
            </a-button>
          </a-popconfirm>
        </template>
      </a-table>
    </div>
    <footer class="table-footer">
      <Pager :total="store.batchTotal" :page-size="store.batchPageSize"
        :current="store.batchPage" @change="changePage" />
    </footer>
  </section>
</template>

<style scoped>
.gpm-batch-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.table-wrap { flex: 1; min-height: 0; overflow: auto; margin: 12px 16px 0; }
.table-footer { display: flex; justify-content: flex-end; padding: 10px 16px; }
.batch-id { color: var(--color-text-2); }
.batch-link { color: rgb(var(--arcoblue-6)); text-decoration: none; }
.batch-link:hover { text-decoration: underline; }
.scene-label { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.delete-button { margin-left: 2px; color: var(--color-text-4); }
.delete-button:hover { color: rgb(var(--red-6)); background: var(--color-fill-2); }
.load-error {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  margin-bottom: 8px; padding: 8px 12px; border-radius: 6px;
  color: rgb(var(--red-6)); background: var(--color-fill-2); font-size: 12px;
}
:deep(.arco-table-td) { padding-top: 4px; padding-bottom: 4px; }
:deep(.arco-table-th) { background: var(--color-fill-2); font-weight: 600; }
:deep(.arco-table-tbody tr:nth-child(even) .arco-table-td) { background: var(--color-fill-1); }
:deep(.arco-table-tbody tr:hover .arco-table-td) { background: var(--color-fill-3); }
</style>
