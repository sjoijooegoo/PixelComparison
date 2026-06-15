<script setup>
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore } from '../store'
import Pager from './Pager.vue'

const store = useStore()

const page = ref(1)
const pageSize = ref(8)   // 按表格区可用高度动态覆盖
const pagedBatches = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return store.batches.slice(start, start + pageSize.value)
})

// 按表格区可用高度动态计算每页行数,填满整列
const tableWrap = ref(null)
let ro
function recalc() {
  const wrap = tableWrap.value
  if (!wrap) return
  const thH = wrap.querySelector('.arco-table-th')?.getBoundingClientRect().height || 36
  const rowH = wrap.querySelector('tbody .arco-table-tr')?.getBoundingClientRect().height || 40
  const fit = Math.max(3, Math.floor((wrap.clientHeight - thH) / rowH))
  if (fit !== pageSize.value) {
    pageSize.value = fit
    if (page.value > Math.ceil(store.batches.length / fit)) page.value = 1
  }
}
onMounted(() => {
  ro = new ResizeObserver(recalc)
  if (tableWrap.value) ro.observe(tableWrap.value)
  recalc()
})
onUnmounted(() => ro?.disconnect())

// 列表刷新/筛选后回到第一页并重算
watch(() => store.batches, () => { page.value = 1; nextTick(recalc) })

const columns = [
  { title: '批次ID', dataIndex: 'id', slotName: 'id' },
  { title: '场景ID', dataIndex: 'scene_id', slotName: 'scene' },
  { title: 'P4版本', dataIndex: 'p4_version', slotName: 'p4', sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '平台', dataIndex: 'platform', slotName: 'platform' },
  { title: '点位数', dataIndex: 'scene_count' },
  { title: '创建时间', dataIndex: 'created_at', sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '操作', slotName: 'ops', width: 200, align: 'right' },
]

// 彩色标签:同值固定同色,让批次表有区分、不单调
const TAG_COLORS = ['arcoblue', 'cyan', 'green', 'orange', 'purple', 'magenta', 'gold', 'lime']
function tagColor(v) {
  let h = 0
  for (const ch of String(v ?? '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return TAG_COLORS[h % TAG_COLORS.length]
}
const PLATFORM_COLOR = { Windows: 'arcoblue', iOS: 'gray', Android: 'green' }
const platformColor = (p) => PLATFORM_COLOR[p] || 'gray'

function setRole(record, role) {
  // 场景守卫:两侧必须同场景ID(同 Level 才能对比)
  const other = role === 'current' ? store.baselineBatch : store.currentBatch
  if (other && other.scene_id !== record.scene_id) {
    Message.warning(`对比批次与基线批次的场景ID需一致(${other.scene_id})`)
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
  const head = '批次ID,场景ID,P4版本,平台,点位数,创建时间'
  const rows = store.batches.map(b =>
    [b.id, b.scene_id, b.p4_version, b.platform, b.scene_count, b.created_at].join(','))
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

    <div class="table-wrap" ref="tableWrap">
      <a-table
        :columns="columns" :data="pagedBatches"
        :pagination="false"
        size="medium" row-key="id"
        :row-class="(r) => roleOf(r) ? 'role-' + roleOf(r) : ''">
        <template #id="{ record }"><span class="mono">#{{ record.id }}</span></template>
        <template #scene="{ record }">
          <a-tag :color="tagColor(record.scene_id)" size="small" bordered>{{ record.scene_id }}</a-tag>
        </template>
        <template #p4="{ record }"><span class="mono">{{ record.p4_version }}</span></template>
        <template #platform="{ record }">
          <a-tag :color="platformColor(record.platform)" size="small">{{ record.platform }}</a-tag>
        </template>
        <template #ops="{ record }">
          <a-button size="mini" :type="roleOf(record) === 'current' ? 'primary' : 'text'"
            @click="setRole(record, 'current')">设为对比</a-button>
          <a-button size="mini" :type="roleOf(record) === 'baseline' ? 'primary' : 'text'"
            :status="roleOf(record) === 'baseline' ? 'normal' : undefined"
            @click="setRole(record, 'baseline')">设为基线</a-button>
        </template>
      </a-table>
    </div>

    <div class="foot">
      <Pager
        :total="store.batchTotal" :page-size="pageSize" :current="page"
        @change="(p) => page = p" />
    </div>
  </section>
</template>

<style scoped>
.batch-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
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

/* 行更舒展:增加单元格上下内边距(不影响列水平对齐) */
:deep(.arco-table-td) { padding-top: 8px; padding-bottom: 8px; }
:deep(.role-current .arco-table-td) { background: rgba(22, 100, 255, .08); box-shadow: inset 2px 0 0 rgb(var(--arcoblue-6)); }
:deep(.role-baseline .arco-table-td) { background: var(--color-fill-2); box-shadow: inset 2px 0 0 var(--color-text-4); }

.table-wrap { flex: 1; min-height: 0; overflow: auto; }
.foot { display: flex; justify-content: flex-end; padding: 10px 16px; }
</style>
