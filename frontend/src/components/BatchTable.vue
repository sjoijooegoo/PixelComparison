<script setup>
import { ref, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { api } from '../api'
import { useStore, STATUS_META } from '../store'

const store = useStore()

const PLATFORM_ICON = { Windows: '🪟', PS5: '🎮', 'Xbox Series X|S': '🟢' }

const columns = [
  { title: '批次ID', dataIndex: 'batch_id', slotName: 'id' },
  { title: '项目', dataIndex: 'project' },
  { title: '分支 / 版本', dataIndex: 'branch' },
  { title: '参照基线 / 批次', dataIndex: 'ref_label', slotName: 'ref' },
  { title: '平台', dataIndex: 'platform', slotName: 'platform' },
  { title: '场景数', dataIndex: 'scene_count' },
  { title: '对比数', dataIndex: 'compare_count' },
  { title: '状态', dataIndex: 'status', slotName: 'status' },
  { title: '差异率(均值)', dataIndex: 'diff_avg', slotName: 'diff', sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '创建人', dataIndex: 'creator' },
  { title: '创建时间', dataIndex: 'created_at', sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '操作', slotName: 'ops', width: 150 },
]

/* ---- 发起对比弹窗 ---- */
const modalVisible = ref(false)
const submitting = ref(false)
const allBatches = ref([])
const baselines = ref([])
const curBatchId = ref('')
const refBatchId = ref('')

async function openModal() {
  const [b, bl] = await Promise.all([api.batches(), api.baselines()])
  allBatches.value = b.items
  baselines.value = bl.items.filter((x) => x.status === 'active')
  curBatchId.value = allBatches.value[0]?.id || ''
  refBatchId.value = ''
  modalVisible.value = true
}

const curBatch = computed(() => allBatches.value.find((b) => b.id === curBatchId.value))

// 参照批次:同项目同平台、排除自身;已晋升基线的批次排在前面并标注版本号
const refOptions = computed(() => {
  if (!curBatch.value) return []
  const baselineByBatch = Object.fromEntries(
    baselines.value.map((b) => [b.source_batch_id, b.version])
  )
  return allBatches.value
    .filter(
      (b) =>
        b.id !== curBatchId.value &&
        b.project === curBatch.value.project &&
        b.platform === curBatch.value.platform
    )
    .map((b) => ({
      id: b.id,
      baseline: baselineByBatch[b.id] || null,
      label: `${baselineByBatch[b.id] ? baselineByBatch[b.id] + ' · ' : ''}#${b.id} (${b.branch})`,
    }))
    .sort((a, b) => (a.baseline ? -1 : 0) - (b.baseline ? -1 : 0))
})

async function submit() {
  if (!curBatchId.value || !refBatchId.value) {
    Message.warning('请选择两个批次')
    return
  }
  submitting.value = true
  try {
    await store.createComparison(curBatchId.value, refBatchId.value)
    modalVisible.value = false
    Message.success('对比完成')
  } catch (e) {
    Message.error(e.message)
  } finally {
    submitting.value = false
  }
}

function batchLabel(b) {
  return `#${b.id} · ${b.branch} · ${b.platform} · ${b.created_at} (${b.scene_count} 场景)`
}

function exportCsv() {
  const head = '批次ID,项目,分支/版本,参照,平台,场景数,对比数,状态,差异率(均值),创建人,创建时间'
  const rows = store.comparisons.map(c =>
    [c.batch_id, c.project, c.branch, c.ref_label, c.platform, c.scene_count, c.compare_count,
     STATUS_META[c.status].label, c.diff_avg + '%', c.creator, c.created_at].join(','))
  const blob = new Blob(['﻿' + head + '\n' + rows.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'shotdiff_comparisons.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <section class="batch-panel panel-border-b">
    <div class="head">
      <h3>批次对比列表 ({{ store.comparisonTotal }})</h3>
      <div style="flex:1"></div>
      <a-button size="small" @click="store.loadComparisons(); Message.success('已刷新')">刷新</a-button>
      <a-button size="small" @click="exportCsv">导出列表</a-button>
      <a-button size="small" type="primary" @click="openModal">发起对比</a-button>
    </div>
    <a-table
      :columns="columns" :data="store.comparisons" :pagination="false"
      size="small" :scroll="{ y: 200 }" row-key="id"
      :row-class="(r) => r.id === store.selectedComparison?.id ? 'row-selected' : ''"
      @row-click="(r) => store.selectComparison(r)">
      <template #id="{ record }"><span class="mono">#{{ record.batch_id }}</span></template>
      <template #ref="{ record }">
        <a-tooltip :content="`参照批次 #${record.ref_batch_id} (${record.ref_branch})`">
          <span>{{ record.ref_label }}</span>
        </a-tooltip>
      </template>
      <template #platform="{ record }">{{ PLATFORM_ICON[record.platform] || '' }} {{ record.platform }}</template>
      <template #status="{ record }">
        <a-tag :color="STATUS_META[record.status].color" size="small">{{ STATUS_META[record.status].label }}</a-tag>
      </template>
      <template #diff="{ record }">
        <span class="mono" :class="{ 'diff-fail': record.status === 'fail' }">{{ record.diff_avg.toFixed(2) }}%</span>
      </template>
      <template #ops="{ record }">
        <a-button size="mini" type="primary" @click.stop="store.selectComparison(record)">查看结果</a-button>
        <a-button size="mini" type="text" @click.stop="Message.info('更多操作:重跑 / 设为基线 / 删除')">⋯</a-button>
      </template>
    </a-table>

    <a-modal v-model:visible="modalVisible" title="发起对比" :width="560">
      <template #footer>
        <a-button @click="modalVisible = false">取消</a-button>
        <a-button type="primary" :loading="submitting" @click="submit">开始对比</a-button>
      </template>
      <div class="form-row">
        <div class="form-label">当前批次(待检查)</div>
        <a-select v-model="curBatchId" placeholder="选择批次" allow-search @change="refBatchId = ''">
          <a-option v-for="b in allBatches" :key="b.id" :value="b.id">{{ batchLabel(b) }}</a-option>
        </a-select>
      </div>
      <div class="form-row">
        <div class="form-label">参照批次(作为基准)</div>
        <a-select v-model="refBatchId" placeholder="选择参照批次或基线" allow-search>
          <a-option v-for="o in refOptions" :key="o.id" :value="o.id">
            <a-tag v-if="o.baseline" color="arcoblue" size="small" style="margin-right:6px">基线 {{ o.baseline }}</a-tag>
            {{ o.label }}
          </a-option>
        </a-select>
        <div class="form-hint text-secondary">仅列出与当前批次同项目、同平台的批次;已晋升为基线的批次优先展示。</div>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.batch-panel { flex: 0 0 auto; }
.head { display: flex; align-items: center; gap: 8px; padding: 10px 16px; }
.head h3 { margin: 0; font-size: 15px; }
:deep(.arco-table-tr) { cursor: pointer; }
:deep(.row-selected .arco-table-td) { background: rgb(var(--arcoblue-1)); }
.form-row { margin-bottom: 16px; }
.form-label { font-size: 12px; color: var(--color-text-2); margin-bottom: 6px; }
.form-hint { font-size: 12px; margin-top: 6px; }
</style>
