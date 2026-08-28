<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useRoute, useRouter } from 'vue-router'
import { batchLocation, batchStateFromFilters } from '../batchRoute'
import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import Pager from './Pager.vue'
import BatchPreview from './BatchPreview.vue'
import { createBatchTableSizer } from './batchTableSizer'
import { qualityLabel } from '../qualityRuns'

const store = useBatchCatalogStore()
const router = useRouter()
const route = useRoute()

function retryBatches() {
  store.loadBatches().catch(() => {})
}

function changePage(page) {
  return router.push(batchLocation(batchStateFromFilters(
    store.filters, page, route.query.return_to || '',
  )))
}

// 批次图片预览弹窗
const previewVisible = ref(false)
const previewBatch = ref(null)
function openPreview(record) {
  if (!record.has_screenshots) return
  previewBatch.value = record
  previewVisible.value = true
}

// 按表格区可用高度动态计算每页行数,填满整列
const tableWrap = ref(null)
const tableSizer = createBatchTableSizer(store)
let mounted = false

async function syncTableWrap() {
  await nextTick()
  if (mounted) tableSizer.observe(tableWrap.value)
}

watch(tableWrap, syncTableWrap, { flush: 'post' })
onMounted(() => {
  mounted = true
  syncTableWrap()
})
onUnmounted(() => {
  mounted = false
  tableSizer.disconnect()
})
// 数据渲染后(行高才量得准)再校正一次每页行数,避免列表填不满高度
watch(() => store.batches.length, () => nextTick(() => {
  if (mounted && tableWrap.value) tableSizer.recalc()
}))

const columns = [
  { title: '批次ID', dataIndex: 'id', slotName: 'id', width: 120 },
  { title: '分支', dataIndex: 'branch_tag', slotName: 'branch', width: 120 },
  { title: '场景ID', dataIndex: 'scene_id', slotName: 'scene', width: 220, ellipsis: true, tooltip: true },
  { title: '平台', dataIndex: 'platform', slotName: 'platform', width: 100 },
  { title: '画质', dataIndex: 'shading_quality_label', slotName: 'quality', width: 160 },
  { title: 'P4版本', dataIndex: 'p4_version', slotName: 'p4', width: 110 },
  { title: '检查点数', dataIndex: 'scene_count', width: 100 },
  { title: '数据', slotName: 'data', width: 120 },
  { title: '创建时间', dataIndex: 'created_at', width: 160, sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '操作', slotName: 'ops', width: 220, align: 'center' },
]

const PLATFORM_COLOR = { Windows: 'arcoblue', iOS: 'gray', Android: 'green' }
const platformColor = (p) => PLATFORM_COLOR[p] || 'gray'

// 画质档位:高→低对应一条由暖到冷的色带
const QUALITY_COLOR = { 电影: 'purple', 极致: 'magenta', 精美: 'arcoblue', 均衡: 'cyan', 流畅: 'green', 节能: 'gray' }
const qualityColor = (q) => QUALITY_COLOR[q] || 'gray'
const qualityValues = (record) => (
  Array.isArray(record.shading_qualities) && record.shading_qualities.length
    ? record.shading_qualities
    : [record.shading_quality].filter((value) => value != null)
)

// 批次详情外链:优先用上报带来的真实流水线链接,旧数据回退到占位地址
const batchLink = (record) => record.batch_url || `https://p4web.example.com/batch/${record.id}`

function dataLabel(record) {
  if (record.has_screenshots && record.has_map_build_data) return '截图 · 烘培'
  if (record.has_screenshots) return '截图'
  if (record.has_map_build_data) return '烘培'
  return '待补传'
}

function dataColor(record) {
  if (record.has_screenshots && record.has_map_build_data) return 'arcoblue'
  if (record.has_screenshots) return 'green'
  if (record.has_map_build_data) return 'purple'
  return 'gray'
}

function openMapBuild(record) {
  if (!record.has_map_build_data) return
  router.push({
    path: `/map-build/${encodeURIComponent(record.scene_id)}`,
    query: { branch_tag: record.branch_tag || 'main', batch: String(record.id) },
  })
}

// 删除单个批次(低调入口:操作列末尾的小垃圾桶 + 二次确认)
const deletingId = ref(null)
async function onDelete(record) {
  deletingId.value = record.id
  try {
    await store.deleteBatch(record.id)
    Message.success(`已删除批次 #${record.id}`)
  } catch (e) {
    Message.error(e.message || '删除失败')
  } finally {
    deletingId.value = null
  }
}


</script>

<template>
  <section class="batch-panel card">
    <div class="table-wrap" ref="tableWrap">
      <div v-if="store.batchError" class="load-error">
        <span>{{ store.batchError }}</span>
        <a-button size="mini" type="primary" @click="retryBatches">重新加载</a-button>
      </div>
      <a-table
        :columns="columns" :data="store.batches"
        :pagination="false"
        :loading="store.batchLoading"
        size="medium" row-key="id">
        <template #id="{ record }">
          <a class="batch-link mono" :href="batchLink(record)" target="_blank" rel="noopener noreferrer">#{{ record.id }}</a>
        </template>
        <template #branch="{ record }">
          <span class="branch-label mono">{{ record.branch_tag || 'main' }}</span>
        </template>
        <template #scene="{ record }">{{ record.scene_id }}</template>
        <template #platform="{ record }">
          <a-tag :color="platformColor(record.platform)" size="small">{{ record.platform }}</a-tag>
        </template>
        <template #quality="{ record }">
          <span class="quality-tags">
            <a-tag v-for="quality in qualityValues(record)" :key="quality"
              :color="qualityColor(qualityLabel(quality))" size="small">
              {{ qualityLabel(quality) }}
            </a-tag>
          </span>
        </template>
        <template #p4="{ record }">
          <span class="mono">{{ record.p4_version ?? '——' }}</span>
        </template>
        <template #data="{ record }">
          <a-tag :color="dataColor(record)" size="small">{{ dataLabel(record) }}</a-tag>
        </template>
        <template #ops="{ record }">
          <a-button size="mini" type="text" :disabled="!record.has_screenshots"
            :title="record.has_screenshots ? '预览截图' : '该批次没有截图数据'"
            @click="openPreview(record)">预览</a-button>
          <a-button size="mini" type="text" :disabled="!record.has_map_build_data"
            :title="record.has_map_build_data ? '查看烘培数据' : '该批次没有烘培数据'"
            @click="openMapBuild(record)">查看烘培数据</a-button>
          <a-popconfirm position="br" type="warning" ok-text="删除" cancel-text="取消"
            :content="`删除批次 #${record.id}?将连带删除它参与的对比、对比项、由其晋升的基线,以及图片/热力图/缩略图,不可恢复。`"
            @ok="onDelete(record)">
            <a-button size="mini" type="text" class="del-btn" title="删除批次"
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

    <div class="foot">
      <Pager
        :total="store.batchTotal" :page-size="store.batchPageSize" :current="store.batchPage"
        @change="changePage" />
    </div>
    <BatchPreview v-model:visible="previewVisible" :batch="previewBatch" />
  </section>
</template>

<style scoped>
.batch-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
/* 删除入口低调:默认浅灰、悬停才变红 */
.del-btn { color: var(--color-text-4); margin-left: 2px; }
.del-btn:hover { color: rgb(var(--red-6)); background: var(--color-fill-2); }
.batch-link { color: rgb(var(--arcoblue-6)); text-decoration: none; }
.batch-link:hover { text-decoration: underline; }
.branch-label { color: var(--color-text-2); font-size: 12px; }
.quality-tags { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 4px; }

/* 行内边距适度紧凑,同样高度能多放几行 */
:deep(.arco-table-td) { padding-top: 4px; padding-bottom: 4px; }
/* 表头分层:背景 + 字重,与数据区分 */
:deep(.arco-table-th) { background: var(--color-fill-2); font-weight: 600; }
/* 隔行斑马纹(淡),长表不串行 */
:deep(.arco-table-tbody tr:nth-child(even) .arco-table-td) { background: var(--color-fill-1); }
/* 行 hover 反馈 */
:deep(.arco-table-tbody tr:hover .arco-table-td) { background: var(--color-fill-3); }

/* 表格区:去掉外层容器整体边框,只保留表格自身随数据变化的行/表头边框 */
.table-wrap {
  flex: 1; min-height: 0; overflow: auto; margin: 12px 16px 0;
}
.load-error {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  margin-bottom: 8px; padding: 8px 12px; border-radius: 6px;
  color: rgb(var(--red-6)); background: var(--color-fill-2); font-size: 12px;
}
.foot { display: flex; justify-content: flex-end; padding: 10px 16px; }
</style>
