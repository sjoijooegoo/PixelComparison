<script setup>
import { computed, reactive, ref } from 'vue'

defineOptions({ name: 'GpmDetailNode' })
const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  expanded: { type: Boolean, default: false },
  expansionState: { type: Object, default: null },
  nodePath: { type: String, default: 'root' },
})
const emit = defineEmits(['toggle'])
const localExpansionState = reactive({})
const state = computed(() => props.expansionState || localExpansionState)
const openChildIndex = computed(() => state.value[props.nodePath] ?? null)
const children = computed(() => {
  if (Array.isArray(props.node.children) && props.node.children.length) return props.node.children
  if (Array.isArray(props.node.treeData) && props.node.treeData.length) return props.node.treeData
  return []
})
const columns = computed(() => props.node.table_data?.cols || [])
const rows = computed(() => props.node.table_data?.data || [])
const sortColumnIndex = ref(null)
const sortDirection = ref('desc')
const sortedRows = computed(() => {
  if (sortColumnIndex.value === null) return rows.value
  const column = columns.value[sortColumnIndex.value]
  return rows.value
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const leftValue = Array.isArray(left.row)
        ? left.row[sortColumnIndex.value]
        : left.row?.[column?.key]
      const rightValue = Array.isArray(right.row)
        ? right.row[sortColumnIndex.value]
        : right.row?.[column?.key]
      const leftEmpty = isEmptyValue(leftValue)
      const rightEmpty = isEmptyValue(rightValue)
      if (leftEmpty || rightEmpty) {
        if (leftEmpty && rightEmpty) return left.index - right.index
        return leftEmpty ? 1 : -1
      }
      const comparison = compareValues(leftValue, rightValue)
      if (comparison === 0) return left.index - right.index
      return sortDirection.value === 'asc' ? comparison : -comparison
    })
    .map((item) => item.row)
})
const nodeTitle = computed(() => String(props.node.name || '未命名数据'))
const hasContent = computed(() => Boolean(children.value.length || columns.value.length))

function toggleChild(index) {
  if (openChildIndex.value === index) delete state.value[props.nodePath]
  else state.value[props.nodePath] = index
}

function compareValues(left, right) {
  const leftText = String(left).trim()
  const rightText = String(right).trim()
  const leftNumber = Number(leftText.replaceAll(',', ''))
  const rightNumber = Number(rightText.replaceAll(',', ''))
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber
  }
  return leftText.localeCompare(rightText, 'zh-CN', { numeric: true, sensitivity: 'base' })
}

function isEmptyValue(value) {
  return value === null || value === undefined || value === ''
}

function toggleSort(columnIndex) {
  if (sortColumnIndex.value === columnIndex) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
    return
  }
  sortColumnIndex.value = columnIndex
  sortDirection.value = 'desc'
}

</script>

<template>
  <div class="detail-node" :class="{ nested: depth > 0, root: depth === 0, open: expanded }">
    <button type="button" class="detail-summary" :class="{ empty: !hasContent }"
      :aria-expanded="hasContent ? expanded : undefined" :disabled="!hasContent"
      @click="hasContent && emit('toggle')">
      <span class="node-title">{{ nodeTitle }}</span>
      <span class="toggle" aria-hidden="true">›</span>
    </button>
    <div v-if="expanded" class="detail-content">
      <div v-if="children.length" class="children-stack">
        <GpmDetailNode v-for="(child, index) in children" :key="`${child.name}-${index}`"
          :node="child" :depth="depth + 1" :expanded="openChildIndex === index"
          :expansion-state="state" :node-path="`${nodePath}.${index}`"
          @toggle="toggleChild(index)" />
      </div>
      <div v-if="columns.length" class="table-scroll">
        <table class="detail-table">
          <thead><tr>
            <th v-for="(column, columnIndex) in columns" :key="column.key"
              :aria-sort="sortColumnIndex === columnIndex
                ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'">
              <button type="button" class="table-sort"
                :title="`按${column.name}${sortColumnIndex === columnIndex
                  ? (sortDirection === 'desc' ? '升序' : '降序') : '降序'}排列`"
                @click="toggleSort(columnIndex)">
                <span>{{ column.name }}</span>
                <span class="sort-mark" :class="{ active: sortColumnIndex === columnIndex }" aria-hidden="true">
                  {{ sortColumnIndex === columnIndex ? (sortDirection === 'asc' ? '↑' : '↓') : '↕' }}
                </span>
              </button>
            </th>
          </tr></thead>
          <tbody>
            <tr v-for="(row, rowIndex) in sortedRows" :key="rowIndex">
              <td v-for="(column, columnIndex) in columns" :key="column.key">
                {{ Array.isArray(row) ? row[columnIndex] : row?.[column.key] }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!children.length && !columns.length" class="empty-node">暂无明细</div>
    </div>
  </div>
</template>

<style scoped>
.detail-node { position: relative; min-width: 0; }
.detail-node.root { border: 1px solid transparent; border-bottom-color: var(--color-border-1); }
.detail-node.root:last-child { border-bottom: 0; }
.detail-summary {
  width: 100%; min-height: 40px; border: 0; padding: 8px 12px;
  display: flex; align-items: center; gap: 12px; text-align: left; cursor: pointer;
  color: var(--color-text-2); background: transparent; font: inherit;
  transition: background-color .12s ease, color .12s ease;
}
.detail-summary:hover { background: var(--color-fill-2); color: var(--color-text-1); }
.detail-summary:focus-visible { outline: 1px solid rgb(var(--arcoblue-5)); outline-offset: -1px; }
.detail-summary:disabled { cursor: not-allowed; color: var(--color-text-4); background: transparent; }
.detail-summary:disabled:hover { color: var(--color-text-4); background: transparent; }
.detail-node.root.open { border-color: var(--color-border-2); }
.detail-node.root.open > .detail-summary { background: var(--color-fill-2); }
.detail-node.nested > .detail-summary { background: var(--color-fill-2); }
.detail-node.nested.open > .detail-summary { color: rgb(var(--arcoblue-6)); }
.toggle {
  margin-left: auto; flex: 0 0 16px; width: 16px; height: 16px; display: grid; place-items: center;
  color: var(--color-text-3); font-size: 18px; line-height: 1;
  transform: rotate(0); transition: transform .15s ease-out, color .12s ease;
}
.open > .detail-summary .toggle { color: rgb(var(--arcoblue-6)); transform: rotate(90deg); }
.detail-summary.empty .toggle { opacity: .28; }
.node-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.detail-content {
  padding: 12px 14px 14px; border-top: 1px solid var(--color-border-1);
  background: color-mix(in srgb, var(--color-fill-2) 74%, var(--color-bg-2));
  animation: detail-reveal .16s ease-out both;
}
.children-stack {
  overflow: hidden; border: 1px solid var(--color-border-2); border-radius: 3px;
  background: var(--color-fill-1);
}
.children-stack > .detail-node { border-bottom: 1px solid var(--color-border-1); }
.children-stack > .detail-node:last-child { border-bottom: 0; }
.table-scroll {
  --detail-table-head-bg: color-mix(in srgb, var(--color-bg-5) 80%, var(--color-bg-white) 20%);
  --detail-table-cell-bg: color-mix(in srgb, var(--color-bg-5) 90%, var(--color-bg-white) 10%);
  max-height: min(440px, 55vh); overflow: auto; border: 1px solid var(--color-border-2);
  border-radius: 3px; background: var(--detail-table-cell-bg);
}
.children-stack + .table-scroll { margin-top: 10px; }
.detail-table { border-collapse: collapse; width: 100%; min-width: 420px; font-size: 12px; }
th, td { text-align: left; border-right: 1px solid var(--color-border-1); border-bottom: 1px solid var(--color-border-1); }
th {
  position: sticky; top: 0; z-index: 1; color: var(--color-text-2); font-weight: 600;
  background: var(--detail-table-head-bg);
}
td {
  padding: 7px 9px; color: var(--color-text-2); background: var(--detail-table-cell-bg);
  font-variant-numeric: tabular-nums;
}
.table-sort {
  width: 100%; min-height: 32px; padding: 7px 9px; border: 0; display: flex;
  align-items: center; justify-content: space-between; gap: 8px; color: inherit;
  background: transparent; font: inherit; font-weight: inherit; text-align: left; cursor: pointer;
}
.table-sort:focus-visible { outline: 1px solid rgb(var(--arcoblue-5)); outline-offset: -2px; }
.sort-mark { color: var(--color-text-4); font-size: 12px; font-weight: 400; }
.sort-mark.active { color: rgb(var(--arcoblue-6)); }
th:first-child, td:first-child { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
th:last-child, td:last-child { border-right: 0; }
.empty-node { padding: 8px; text-align: center; color: var(--color-text-3); font-size: 12px; }
@keyframes detail-reveal {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .detail-summary, .toggle { transition: none; }
  .detail-content { animation: none; }
}
</style>
