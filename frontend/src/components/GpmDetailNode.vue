<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { vOverflowTitle } from '../directives/overflowTitle'
import { detailNodePath } from '../gpmHeatmap/detailPaths'

defineOptions({ name: 'GpmDetailNode' })
const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  expanded: { type: Boolean, default: false },
  expansionState: { type: Object, default: null },
  tableSortState: { type: Object, default: null },
  nodePath: { type: String, default: 'root' },
})
const emit = defineEmits(['toggle'])
const localExpansionState = reactive({})
const localTableSortState = reactive({})
const state = computed(() => props.expansionState || localExpansionState)
const sortState = computed(() => props.tableSortState || localTableSortState)
const openChildPath = computed(() => state.value[props.nodePath] ?? null)
const children = computed(() => {
  if (Array.isArray(props.node.children) && props.node.children.length) return props.node.children
  if (Array.isArray(props.node.treeData) && props.node.treeData.length) return props.node.treeData
  return []
})
const columns = computed(() => (
  Array.isArray(props.node.table_data?.cols) ? props.node.table_data.cols : []
))
const rows = computed(() => (
  Array.isArray(props.node.table_data?.data) ? props.node.table_data.data : []
))
const savedSort = sortState.value[props.nodePath]
const savedSortColumnIndex = savedSort
  ? columns.value.findIndex((column) => (column.key || column.name) === savedSort.columnKey)
  : -1
const sortColumnIndex = ref(savedSortColumnIndex >= 0 ? savedSortColumnIndex : null)
const sortDirection = ref(savedSort?.direction === 'asc' ? 'asc' : 'desc')
const currentPage = ref(1)
const tableElement = ref(null)
const columnWidths = ref([])
const resizingColumnIndex = ref(null)
const pageSize = 15
const minimumColumnWidth = 88
let resizeSession = null
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
const totalPages = computed(() => Math.max(1, Math.ceil(sortedRows.value.length / pageSize)))
const visiblePages = computed(() => {
  const count = Math.min(5, totalPages.value)
  const start = Math.min(
    Math.max(1, currentPage.value - Math.floor(count / 2)),
    totalPages.value - count + 1,
  )
  return Array.from({ length: count }, (_, index) => start + index)
})
const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return sortedRows.value.slice(start, start + pageSize)
})
const nodeTitle = computed(() => String(props.node.name || '未命名数据'))
const hasContent = computed(() => Boolean(children.value.length || columns.value.length))
const effectiveExpanded = computed(() => props.expanded && hasContent.value)
const tableStyle = computed(() => {
  if (columnWidths.value.length !== columns.value.length) return undefined
  const width = columnWidths.value.reduce((total, value) => total + value, 0)
  return { width: `${width}px`, minWidth: '100%', tableLayout: 'fixed' }
})

watch(() => columns.value.map((column, index) => (
  `${column?.key || column?.name || 'column'}:${index}`
)).join('|'), () => {
  finishColumnResize()
  columnWidths.value = []
})

watch(() => sortedRows.value.length, () => {
  currentPage.value = Math.min(currentPage.value, totalPages.value)
})

onBeforeUnmount(finishColumnResize)

function childPath(index) {
  return detailNodePath(props.nodePath, children.value, index)
}

function toggleChild(path) {
  if (openChildPath.value === path) delete state.value[props.nodePath]
  else state.value[props.nodePath] = path
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

function cellValue(row, column, columnIndex) {
  return Array.isArray(row) ? row[columnIndex] : row?.[column.key]
}

function cellTitle(row, column, columnIndex) {
  const value = cellValue(row, column, columnIndex)
  return value === null || value === undefined ? '' : String(value)
}

function externalLink(value) {
  if (typeof value !== 'string') return ''
  const candidate = value.trim()
  if (!candidate) return ''
  try {
    const protocol = new URL(candidate).protocol
    return protocol === 'http:' || protocol === 'https:' ? candidate : ''
  } catch {
    return ''
  }
}

function excelOpenLink(value) {
  const link = externalLink(value)
  if (!link) return ''
  try {
    if (!new URL(link).pathname.toLowerCase().endsWith('.csv')) return ''
    return `ms-excel:ofv|u|${link}`
  } catch {
    return ''
  }
}

function toggleSort(columnIndex) {
  currentPage.value = 1
  if (sortColumnIndex.value === columnIndex) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumnIndex.value = columnIndex
    sortDirection.value = 'desc'
  }
  const column = columns.value[columnIndex]
  sortState.value[props.nodePath] = {
    columnKey: column?.key || column?.name,
    direction: sortDirection.value,
  }
}

function changePage(offset) {
  currentPage.value = Math.min(totalPages.value, Math.max(1, currentPage.value + offset))
}

function goToPage(page) {
  currentPage.value = Math.min(totalPages.value, Math.max(1, page))
}

function currentColumnWidths() {
  const headers = tableElement.value?.querySelectorAll('thead th') || []
  return Array.from(headers, (header) => Math.max(
    minimumColumnWidth,
    header.getBoundingClientRect().width || header.offsetWidth || minimumColumnWidth,
  ))
}

function setResizedWidth(index, delta, sourceWidths) {
  if (index < 0 || index >= sourceWidths.length - 1) return
  const constrainedDelta = Math.min(
    sourceWidths[index + 1] - minimumColumnWidth,
    Math.max(minimumColumnWidth - sourceWidths[index], delta),
  )
  const nextWidths = [...sourceWidths]
  nextWidths[index] = sourceWidths[index] + constrainedDelta
  nextWidths[index + 1] = sourceWidths[index + 1] - constrainedDelta
  columnWidths.value = nextWidths
}

function startColumnResize(columnIndex, event) {
  if (event.button !== 0) return
  const widths = currentColumnWidths()
  if (widths.length !== columns.value.length) return

  event.preventDefault()
  resizeSession = {
    columnIndex,
    startX: event.clientX,
    widths,
  }
  columnWidths.value = widths
  resizingColumnIndex.value = columnIndex
  document.body.classList.add('gpm-column-resizing')
  window.addEventListener('mousemove', moveColumnResize)
  window.addEventListener('mouseup', finishColumnResize)
  window.addEventListener('blur', finishColumnResize)
}

function moveColumnResize(event) {
  if (!resizeSession) return
  setResizedWidth(
    resizeSession.columnIndex,
    event.clientX - resizeSession.startX,
    resizeSession.widths,
  )
}

function finishColumnResize() {
  resizeSession = null
  resizingColumnIndex.value = null
  document.body.classList.remove('gpm-column-resizing')
  window.removeEventListener('mousemove', moveColumnResize)
  window.removeEventListener('mouseup', finishColumnResize)
  window.removeEventListener('blur', finishColumnResize)
}

function resizeColumnByKeyboard(columnIndex, event) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const widths = currentColumnWidths()
  if (widths.length !== columns.value.length) return
  setResizedWidth(
    columnIndex,
    event.key === 'ArrowRight' ? 12 : -12,
    widths,
  )
}

</script>

<template>
  <div class="detail-node" :class="{ nested: depth > 0, root: depth === 0, open: effectiveExpanded }">
    <button type="button" class="detail-summary" :class="{ empty: !hasContent }"
      :aria-expanded="hasContent ? effectiveExpanded : undefined" :disabled="!hasContent"
      @click="hasContent && emit('toggle')">
      <span class="node-title">{{ nodeTitle }}</span>
      <span class="toggle" aria-hidden="true">›</span>
    </button>
    <div v-if="effectiveExpanded" class="detail-content"
      :class="{ paginated: columns.length && totalPages > 1 }">
      <div v-if="children.length" class="children-stack">
        <GpmDetailNode v-for="(child, index) in children" :key="childPath(index)"
          :node="child" :depth="depth + 1" :expanded="openChildPath === childPath(index)"
          :expansion-state="state" :table-sort-state="sortState"
          :node-path="childPath(index)"
          @toggle="toggleChild(childPath(index))" />
      </div>
      <div v-if="columns.length" class="table-scroll"
        :class="{ resizing: resizingColumnIndex !== null }">
        <table ref="tableElement" class="detail-table" :style="tableStyle">
          <colgroup v-if="columnWidths.length === columns.length">
            <col v-for="(column, columnIndex) in columns"
              :key="column.key || column.name || columnIndex"
              :style="{ width: `${columnWidths[columnIndex]}px` }">
          </colgroup>
          <thead><tr>
            <th v-for="(column, columnIndex) in columns" :key="column.key || column.name || columnIndex"
              :class="{ 'is-resizing': resizingColumnIndex === columnIndex }"
              :aria-sort="sortColumnIndex === columnIndex
                ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'">
              <button type="button" class="table-sort"
                :aria-label="`按${column.name}${sortColumnIndex === columnIndex
                  ? (sortDirection === 'desc' ? '升序' : '降序') : '降序'}排列`"
                @click="toggleSort(columnIndex)">
                <span>{{ column.name }}</span>
                <span class="sort-mark" :class="{ active: sortColumnIndex === columnIndex }" aria-hidden="true">
                  {{ sortColumnIndex === columnIndex ? (sortDirection === 'asc' ? '↑' : '↓') : '↕' }}
                </span>
              </button>
              <span v-if="columnIndex < columns.length - 1" class="column-resizer"
                role="separator" tabindex="0"
                aria-orientation="vertical" :aria-label="`调整${column.name || `第 ${columnIndex + 1} 列`}宽度`"
                @mousedown.stop="startColumnResize(columnIndex, $event)"
                @click.stop.prevent @keydown.stop="resizeColumnByKeyboard(columnIndex, $event)" />
            </th>
          </tr></thead>
          <tbody>
            <tr v-for="(row, rowIndex) in pagedRows"
              :key="`${currentPage}-${rowIndex}`">
              <td v-for="(column, columnIndex) in columns" :key="column.key || column.name || columnIndex">
                <div v-if="externalLink(cellValue(row, column, columnIndex))" class="linked-cell">
                  <a v-overflow-title="cellTitle(row, column, columnIndex)"
                    class="cell-content detail-link"
                    :href="externalLink(cellValue(row, column, columnIndex))"
                    target="_blank" rel="noopener noreferrer">
                    {{ cellValue(row, column, columnIndex) }}
                  </a>
                  <a v-if="excelOpenLink(cellValue(row, column, columnIndex))"
                    class="excel-open-link"
                    :href="excelOpenLink(cellValue(row, column, columnIndex))"
                    :aria-label="`用 Excel 打开 ${cellTitle(row, column, columnIndex)}`">
                    <span>用 Excel 打开</span>
                  </a>
                </div>
                <span v-else v-overflow-title="cellTitle(row, column, columnIndex)" class="cell-content">
                  {{ cellValue(row, column, columnIndex) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer v-if="columns.length && totalPages > 1" class="table-pagination"
        :aria-label="`表格分页，共 ${sortedRows.length} 条`">
        <button type="button" class="page-arrow" aria-label="上一页"
          :disabled="currentPage === 1" @click="changePage(-1)">‹</button>
        <button v-for="page in visiblePages" :key="page" type="button"
          class="page-number" :class="{ active: page === currentPage }"
          :aria-current="page === currentPage ? 'page' : undefined"
          :aria-label="`第 ${page} 页`" @click="goToPage(page)">{{ page }}</button>
        <button type="button" class="page-arrow" aria-label="下一页"
          :disabled="currentPage === totalPages" @click="changePage(1)">›</button>
      </footer>
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
.detail-content.paginated { padding-bottom: 5px; }
.children-stack {
  overflow: hidden; border: 1px solid var(--color-border-2); border-radius: 3px;
  background: var(--color-fill-1);
}
.children-stack > .detail-node { border-bottom: 1px solid var(--color-border-1); }
.children-stack > .detail-node:last-child { border-bottom: 0; }
.table-scroll {
  --detail-table-head-bg: color-mix(in srgb, var(--color-bg-5) 80%, var(--color-bg-white) 20%);
  --detail-table-cell-bg: color-mix(in srgb, var(--color-bg-5) 90%, var(--color-bg-white) 10%);
  overflow-x: auto; overflow-y: hidden; border: 1px solid var(--color-border-2);
  border-radius: 3px; background: var(--detail-table-cell-bg);
}
.table-scroll.resizing { cursor: col-resize; }
.children-stack + .table-scroll { margin-top: 10px; }
.detail-table { border-collapse: collapse; width: 100%; min-width: 420px; font-size: 12px; }
th, td {
  overflow: hidden; text-align: left;
  border-right: 1px solid var(--color-border-1); border-bottom: 1px solid var(--color-border-1);
}
th {
  position: sticky; top: 0; z-index: 1; color: var(--color-text-2); font-weight: 600;
  background: var(--detail-table-head-bg);
}
td {
  min-width: 0; padding: 7px 9px; color: var(--color-text-2); background: var(--detail-table-cell-bg);
  font-variant-numeric: tabular-nums;
}
.cell-content {
  display: block; min-width: 0; width: 100%; overflow: hidden;
  margin-bottom: -2px; padding-bottom: 2px;
  text-overflow: ellipsis; white-space: nowrap;
}
.linked-cell { width: 100%; min-width: 0; display: flex; align-items: center; gap: 10px; }
.linked-cell > .cell-content { flex: 1 1 auto; width: auto; }
.detail-link {
  color: rgb(var(--arcoblue-5)); text-decoration: none;
}
.detail-link:hover { color: rgb(var(--arcoblue-4)); text-decoration: underline; }
.detail-link:focus-visible { outline: 1px solid rgb(var(--arcoblue-5)); outline-offset: 2px; }
.excel-open-link {
  flex: 0 0 auto; min-height: 22px; padding: 0 7px; border: 1px solid rgba(51, 160, 111, .46);
  border-radius: 4px; display: inline-flex; align-items: center;
  color: #63c99a; background: rgba(33, 115, 70, .15); font-size: 11px; font-weight: 600;
  line-height: 1; text-decoration: none; white-space: nowrap;
  transition: color .12s ease, background-color .12s ease, border-color .12s ease;
}
.excel-open-link:hover {
  color: #83ddb4; background: rgba(33, 115, 70, .25); border-color: rgba(74, 190, 135, .68);
}
.excel-open-link:active { background: rgba(33, 115, 70, .34); }
.excel-open-link:focus-visible { outline: 1px solid #63c99a; outline-offset: 2px; }
.table-sort {
  width: 100%; min-height: 32px; padding: 7px 14px 7px 9px; border: 0; display: flex;
  align-items: center; justify-content: space-between; gap: 8px; color: inherit;
  background: transparent; font: inherit; font-weight: inherit; text-align: left; cursor: pointer;
}
.table-sort > span:first-child {
  min-width: 0; overflow: hidden; margin-bottom: -2px; padding-bottom: 2px;
  text-overflow: ellipsis; white-space: nowrap;
}
.table-sort:focus-visible { outline: 1px solid rgb(var(--arcoblue-5)); outline-offset: -2px; }
.column-resizer {
  position: absolute; z-index: 3; top: 0; right: 0; width: 10px; height: 100%;
  cursor: col-resize; touch-action: none;
}
.column-resizer::after {
  content: ''; position: absolute; top: 4px; right: 0; bottom: 4px; width: 1px;
  border-radius: 1px; background: rgb(var(--arcoblue-5)); opacity: 0;
  transition: opacity .12s ease;
}
.column-resizer:hover::after,
.column-resizer:focus-visible::after,
th.is-resizing > .column-resizer::after { opacity: 1; }
.column-resizer:focus-visible { outline: none; }
:global(body.gpm-column-resizing) { cursor: col-resize !important; user-select: none !important; }
.sort-mark { color: var(--color-text-4); font-size: 12px; font-weight: 400; }
.sort-mark.active { color: rgb(var(--arcoblue-6)); }
th:first-child, td:first-child { max-width: 360px; }
tr:last-child td { border-bottom: 0; }
th:last-child, td:last-child { border-right: 0; }
.table-pagination {
  min-height: 32px; margin-top: 5px; padding: 3px 0; display: flex;
  align-items: center; justify-content: flex-start; gap: 4px;
  background: transparent;
  color: var(--color-text-3); font-size: 12px; font-variant-numeric: tabular-nums;
}
.table-pagination button {
  width: 26px; height: 26px; padding: 0; border: 1px solid transparent;
  border-radius: 4px; background: transparent; color: var(--color-text-2);
  display: grid; place-items: center; line-height: 1;
  font: inherit; font-weight: 600; cursor: pointer;
  transition: background-color .12s ease, border-color .12s ease, color .12s ease;
}
.table-pagination button:hover:not(:disabled) {
  border-color: var(--color-border-2); background: color-mix(in srgb, var(--color-fill-3) 58%, transparent);
}
.table-pagination .page-number.active {
  border-color: rgba(var(--arcoblue-6), .46);
  background: rgba(var(--arcoblue-6), .16); color: rgb(var(--arcoblue-5));
}
.table-pagination .page-arrow { color: var(--color-text-3); font-size: 18px; font-weight: 400; }
.table-pagination button:focus-visible {
  outline: 1px solid rgb(var(--arcoblue-5)); outline-offset: 1px;
}
.table-pagination button:disabled { opacity: .42; cursor: not-allowed; }
.empty-node { padding: 8px; text-align: center; color: var(--color-text-3); font-size: 12px; }
@keyframes detail-reveal {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .detail-summary, .toggle, .excel-open-link { transition: none; }
  .detail-content { animation: none; }
}
</style>
