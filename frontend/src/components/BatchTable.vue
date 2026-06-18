<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore } from '../store'
import Pager from './Pager.vue'
import BatchPreview from './BatchPreview.vue'
import BatchGrid from './BatchGrid.vue'

const store = useStore()

// 视图切换:list(列表) / grid(列表图);切到 grid 时按当前场景拉矩阵
function onViewChange() {
  if (store.batchView === 'grid') store.loadGrid()
}

// 批次图片预览弹窗
const previewVisible = ref(false)
const previewBatch = ref(null)
function openPreview(record) {
  previewBatch.value = record
  previewVisible.value = true
}

// 按表格区可用高度动态计算每页行数,填满整列
const tableWrap = ref(null)
let ro
function recalc() {
  const wrap = tableWrap.value
  if (!wrap) return
  const thH = wrap.querySelector('.arco-table-th')?.getBoundingClientRect().height || 36
  const rowH = wrap.querySelector('tbody .arco-table-tr')?.getBoundingClientRect().height || 40
  const fit = Math.max(3, Math.floor((wrap.clientHeight - thH) / rowH))
  if (fit !== store.batchPageSize) {
    store.batchPageSize = fit
    store.batchPage = 1
    store.loadBatches()
  }
}
onMounted(() => {
  ro = new ResizeObserver(recalc)
  if (tableWrap.value) ro.observe(tableWrap.value)
  recalc()
})
onUnmounted(() => ro?.disconnect())
// 数据渲染后(行高才量得准)再校正一次每页行数,避免列表填不满高度
watch(() => store.batches.length, () => nextTick(recalc))

const columns = [
  { title: '批次ID', dataIndex: 'id', slotName: 'id', width: 120 },
  { title: '场景ID', dataIndex: 'scene_id', slotName: 'scene', width: 220, ellipsis: true, tooltip: true },
  { title: '平台', dataIndex: 'platform', slotName: 'platform', width: 100 },
  { title: '画质', dataIndex: 'shading_quality_label', slotName: 'quality', width: 90 },
  { title: '检查点数', dataIndex: 'scene_count', width: 100 },
  { title: '创建时间', dataIndex: 'created_at', width: 160, sortable: { sortDirections: ['ascend', 'descend'] } },
  { title: '操作', slotName: 'ops', width: 270, align: 'center' },
]

const PLATFORM_COLOR = { Windows: 'arcoblue', iOS: 'gray', Android: 'green' }
const platformColor = (p) => PLATFORM_COLOR[p] || 'gray'

// 画质档位:高→低对应一条由暖到冷的色带
const QUALITY_COLOR = { 电影: 'purple', 极致: 'magenta', 精美: 'arcoblue', 均衡: 'cyan', 流畅: 'green', 节能: 'gray' }
const qualityColor = (q) => QUALITY_COLOR[q] || 'gray'

// 批次详情外链:优先用上报带来的真实流水线链接,旧数据回退到占位地址
const batchLink = (record) => record.batch_url || `https://p4web.example.com/batch/${record.id}`

function setRole(record, role) {
  // 选择时不限制,允许自由换批次;场景一致性在「发起对比」时校验
  store.setRole(record, role)
}

async function run() {
  if (!store.canCompare) return
  // 场景守卫:两侧必须同场景ID(同 Level 才能对比)
  if (store.currentBatch.scene_id !== store.baselineBatch.scene_id) {
    Message.warning('对比批次与基线批次需为同一场景ID(同 Level)')
    return
  }
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


</script>

<template>
  <section class="batch-panel card">
    <div class="head">
      <h3>批次列表 ({{ store.batchTotal }})</h3>
      <div style="flex:1"></div>
      <a-radio-group v-model="store.batchView" type="button" size="small" @change="onViewChange">
        <a-radio value="list">列表</a-radio>
        <a-radio value="grid">列表图</a-radio>
      </a-radio-group>
    </div>

    <!-- 选择条:已选的对比批次 / 基线批次 + 发起对比(两种视图都可用) -->
    <div class="select-bar">
      <div class="slot">
        <span class="slot-tag slot-base">基线批次</span>
        <template v-if="store.baselineBatch">
          <span class="mono">#{{ store.baselineBatch.id }}</span>
          <button class="slot-x" @click="store.clearRole('baseline')">×</button>
        </template>
        <span v-else class="slot-empty">未选择</span>
      </div>
      <span class="vs">VS</span>
      <div class="slot">
        <span class="slot-tag slot-cur">对比批次</span>
        <template v-if="store.currentBatch">
          <span class="mono">#{{ store.currentBatch.id }}</span>
          <button class="slot-x" @click="store.clearRole('current')">×</button>
        </template>
        <span v-else class="slot-empty">未选择</span>
      </div>
      <a-button type="primary" size="medium" class="run-btn" :disabled="!store.canCompare"
        :loading="store.running" @click="run">
        {{ store.running && store.progress.total ? `对比中 ${store.progress.done}/${store.progress.total}` : '发起对比' }}
      </a-button>
    </div>

    <div v-if="store.batchView === 'list'" class="table-wrap" ref="tableWrap">
      <a-table
        :columns="columns" :data="store.batches"
        :pagination="false"
        size="medium" row-key="id">
        <template #id="{ record }">
          <a class="batch-link mono" :href="batchLink(record)" target="_blank" rel="noopener noreferrer">#{{ record.id }}</a>
        </template>
        <template #scene="{ record }">{{ record.scene_id }}</template>
        <template #platform="{ record }">
          <a-tag :color="platformColor(record.platform)" size="small">{{ record.platform }}</a-tag>
        </template>
        <template #quality="{ record }">
          <a-tag :color="qualityColor(record.shading_quality_label)" size="small">{{ record.shading_quality_label }}</a-tag>
        </template>
        <template #ops="{ record }">
          <a-button size="mini" type="text" @click="openPreview(record)">预览</a-button>
          <a-button size="mini" :type="roleOf(record) === 'baseline' ? 'primary' : 'text'"
            :style="roleOf(record) === 'baseline'
              ? { background: 'rgb(var(--batch-base))', borderColor: 'rgb(var(--batch-base))', color: '#fff' }
              : { color: 'rgb(var(--batch-base))' }"
            @click="setRole(record, 'baseline')">设为基线</a-button>
          <a-button size="mini" :type="roleOf(record) === 'current' ? 'primary' : 'text'"
            :style="roleOf(record) === 'current'
              ? { background: 'rgb(var(--batch-cur))', borderColor: 'rgb(var(--batch-cur))', color: '#fff' }
              : { color: 'rgb(var(--batch-cur))' }"
            @click="setRole(record, 'current')">设为对比</a-button>
        </template>
      </a-table>
    </div>

    <div v-if="store.batchView === 'list'" class="foot">
      <Pager
        :total="store.batchTotal" :page-size="store.batchPageSize" :current="store.batchPage"
        @change="(p) => { store.batchPage = p; store.loadBatches() }" />
    </div>

    <!-- 列表图:同场景多批次图片矩阵 -->
    <BatchGrid v-else />

    <BatchPreview v-model:visible="previewVisible" :batch="previewBatch" />
  </section>
</template>

<style scoped>
.batch-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.head { display: flex; align-items: center; gap: 8px; padding: 10px 16px; }
.head h3 { margin: 0; font-size: 14px; }

.select-bar {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  margin: 0 12px 10px; background: var(--color-fill-1); border-radius: 8px;
}
.run-btn { margin-left: auto; }
.batch-link { color: rgb(var(--arcoblue-6)); text-decoration: none; }
.batch-link:hover { text-decoration: underline; }
.slot { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.slot-tag { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; }
.slot-cur { background: rgba(var(--batch-cur), .16); color: rgb(var(--batch-cur)); }
.slot-base { background: rgba(var(--batch-base), .16); color: rgb(var(--batch-base)); }
.slot-empty { color: var(--color-text-4); }
.slot-x {
  border: none; background: none; cursor: pointer; color: var(--color-text-3);
  font-size: 14px; line-height: 1; padding: 0 2px;
}
.slot-x:hover { color: rgb(var(--red-6)); }
.vs { font-size: 11px; font-weight: 700; color: var(--color-text-4); }

/* 行内边距适度紧凑,同样高度能多放几行 */
:deep(.arco-table-td) { padding-top: 4px; padding-bottom: 4px; }
/* 表头分层:背景 + 字重,与数据区分 */
:deep(.arco-table-th) { background: var(--color-fill-2); font-weight: 600; }
/* 隔行斑马纹(淡),长表不串行 */
:deep(.arco-table-tbody tr:nth-child(even) .arco-table-td) { background: var(--color-fill-1); }
/* 行 hover 反馈 */
:deep(.arco-table-tbody tr:hover .arco-table-td) { background: var(--color-fill-3); }

/* 与列表图一致:圆角边框容器,左右内缩与表头/分页对齐 */
.table-wrap {
  flex: 1; min-height: 0; overflow: auto; margin: 0 16px;
  border: 1px solid var(--color-border-2); border-radius: 8px;
}
.foot { display: flex; justify-content: flex-end; padding: 10px 16px; }
</style>
