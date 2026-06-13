<script setup>
import { Message } from '@arco-design/web-vue'
import { useStore } from '../store'

const store = useStore()

const columns = [
  { title: '批次ID', dataIndex: 'id', slotName: 'id' },
  { title: '项目', dataIndex: 'project' },
  { title: '分支 / 版本', dataIndex: 'branch' },
  { title: '平台', dataIndex: 'platform' },
  { title: '场景数', dataIndex: 'scene_count' },
  { title: '创建时间', dataIndex: 'created_at', sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '操作', slotName: 'ops', width: 200 },
]

function setRole(record, role) {
  // 平台守卫:两侧必须同平台
  const other = role === 'current' ? store.baselineBatch : store.currentBatch
  if (other && other.platform !== record.platform) {
    Message.warning(`对比批次与基线批次的平台需一致(${other.platform})`)
    return
  }
  store.setRole(record, role)
}

async function run() {
  if (!store.canCompare) return
  try {
    await store.runComparison()
    Message.success('对比完成')
  } catch (e) {
    Message.error(e.message || '对比失败')
  }
}

function roleOf(record) {
  if (store.currentBatch?.id === record.id) return 'current'
  if (store.baselineBatch?.id === record.id) return 'baseline'
  return null
}

function exportCsv() {
  const head = '批次ID,项目,分支/版本,平台,场景数,创建时间'
  const rows = store.batches.map(b =>
    [b.id, b.project, b.branch, b.platform, b.scene_count, b.created_at].join(','))
  const blob = new Blob(['﻿' + head + '\n' + rows.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'pixelcomparison_batches.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <section class="batch-panel card">
    <div class="head">
      <h3>批次列表 ({{ store.batchTotal }})</h3>
      <div style="flex:1"></div>
      <a-button size="small" @click="store.loadBatches(); Message.success('已刷新')">刷新</a-button>
      <a-button size="small" @click="exportCsv">导出列表</a-button>
    </div>

    <!-- 选择条:已选的对比批次 / 基线批次 + 发起对比 -->
    <div class="select-bar">
      <div class="slot">
        <span class="slot-tag slot-cur">对比批次</span>
        <template v-if="store.currentBatch">
          <span class="mono">#{{ store.currentBatch.id }}</span>
          <button class="slot-x" @click="store.clearRole('current')">×</button>
        </template>
        <span v-else class="slot-empty">未选择</span>
      </div>
      <span class="vs">VS</span>
      <div class="slot">
        <span class="slot-tag slot-base">基线批次</span>
        <template v-if="store.baselineBatch">
          <span class="mono">#{{ store.baselineBatch.id }}</span>
          <button class="slot-x" @click="store.clearRole('baseline')">×</button>
        </template>
        <span v-else class="slot-empty">未选择</span>
      </div>
      <a-button type="primary" size="small" :disabled="!store.canCompare"
        :loading="store.running" @click="run">发起对比</a-button>
    </div>

    <a-table
      :columns="columns" :data="store.batches"
      :pagination="{ pageSize: 5, size: 'small', showTotal: true, hideOnSinglePage: false }"
      size="small" row-key="id"
      :row-class="(r) => roleOf(r) ? 'role-' + roleOf(r) : ''">
      <template #id="{ record }"><span class="mono">#{{ record.id }}</span></template>
      <template #ops="{ record }">
        <a-button size="mini" :type="roleOf(record) === 'current' ? 'primary' : 'text'"
          @click="setRole(record, 'current')">设为对比</a-button>
        <a-button size="mini" :type="roleOf(record) === 'baseline' ? 'primary' : 'text'"
          :status="roleOf(record) === 'baseline' ? 'normal' : undefined"
          @click="setRole(record, 'baseline')">设为基线</a-button>
      </template>
    </a-table>
  </section>
</template>

<style scoped>
.batch-panel { flex: 0 0 auto; }
.head { display: flex; align-items: center; gap: 8px; padding: 10px 16px; }
.head h3 { margin: 0; font-size: 14px; }

.select-bar {
  display: flex; align-items: center; gap: 12px; padding: 8px 16px;
  margin: 0 12px 8px; background: var(--color-fill-1); border-radius: 8px;
}
.slot { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.slot-tag { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; }
.slot-cur { background: rgba(22, 100, 255, .15); color: rgb(var(--arcoblue-6)); }
.slot-base { background: var(--color-fill-3); color: var(--color-text-2); }
.slot-empty { color: var(--color-text-4); }
.slot-x {
  border: none; background: none; cursor: pointer; color: var(--color-text-3);
  font-size: 14px; line-height: 1; padding: 0 2px;
}
.slot-x:hover { color: rgb(var(--red-6)); }
.vs { font-size: 11px; font-weight: 700; color: var(--color-text-4); }

:deep(.role-current .arco-table-td) { background: rgba(22, 100, 255, .08); box-shadow: inset 2px 0 0 rgb(var(--arcoblue-6)); }
:deep(.role-baseline .arco-table-td) { background: var(--color-fill-2); box-shadow: inset 2px 0 0 var(--color-text-4); }
</style>
