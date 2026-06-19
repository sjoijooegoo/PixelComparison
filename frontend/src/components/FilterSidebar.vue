<script setup>
import { ref, computed } from 'vue'
import { useStore, defaultDateRange } from '../store'

const store = useStore()

// 创建时间范围:绑定到 filters.created_from/created_to(YYYY-MM-DD)
const dateRange = computed(() => {
  const { created_from, created_to } = store.filters
  return created_from && created_to ? [created_from, created_to] : undefined
})

// 「指定日期」模式下用于逐个添加的选择器(选完即清空,可继续添加)
const dayPick = ref(null)

// 任意筛选项变更即自动应用(静默)
async function applyNow() {
  store.batchPage = 1
  await store.loadBatches()
  if (store.batchView === 'grid') await store.loadGrid()
}

function onDateChange(v) {
  if (v?.[0] && v?.[1]) {
    store.filters.created_from = v[0]
    store.filters.created_to = v[1]
  } else {
    // 不允许清空成全部时间,恢复默认近七天
    Object.assign(store.filters, defaultDateRange())
  }
  applyNow()
}

// 切换 范围 / 指定日期 模式
function onModeChange() {
  applyNow()
}

// 添加一个指定日期(去重 + 升序);选完清空选择器
function addDay(d) {
  if (!d) return
  const set = new Set(store.filters.created_dates)
  set.add(d)
  store.filters.created_dates = [...set].sort()
  dayPick.value = null
  applyNow()
}

function removeDay(d) {
  store.filters.created_dates = store.filters.created_dates.filter((x) => x !== d)
  applyNow()
}

async function reset() {
  // 创建时间始终保留(恢复默认近七天),不放出全部时间数据
  store.filters = { scene_id: '', shading_quality: null, dateMode: 'range', ...defaultDateRange(), created_dates: [], status: '' }
  dayPick.value = null
  await applyNow()
}
</script>

<template>
  <div class="filter-bar card">
    <div class="field">
      <span class="label">场景ID</span>
      <a-select v-model="store.filters.scene_id" placeholder="全部场景" allow-clear allow-search size="small"
        style="width: 320px" @change="applyNow">
        <a-option v-for="s in store.meta.scene_ids" :key="s" :value="s">{{ s }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">创建时间</span>
      <a-radio-group v-model="store.filters.dateMode" type="button" size="small" @change="onModeChange">
        <a-radio value="range">范围</a-radio>
        <a-radio value="days">指定日期</a-radio>
      </a-radio-group>
      <template v-if="store.filters.dateMode === 'range'">
        <a-range-picker size="small" style="width: 230px" :allow-clear="false"
          :model-value="dateRange" @change="onDateChange" />
      </template>
      <template v-else>
        <a-date-picker size="small" style="width: 140px" placeholder="添加日期"
          value-format="YYYY-MM-DD" :model-value="dayPick" @change="addDay" />
        <div class="days">
          <a-tag v-for="d in store.filters.created_dates" :key="d" closable size="small"
            color="arcoblue" @close="removeDay(d)">{{ d }}</a-tag>
          <span v-if="!store.filters.created_dates.length" class="days-hint">未选日期 = 不限</span>
        </div>
      </template>
    </div>
    <div class="spacer"></div>
    <a-button size="small" @click="reset">清空</a-button>
  </div>
</template>

<style scoped>
.filter-bar {
  flex: 0 0 auto;
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px 16px; padding: 10px 14px;
}
.field { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.field .label { color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.days { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; max-width: 360px; }
.days-hint { color: var(--color-text-4); font-size: 12px; }
.spacer { flex: 1; }
</style>
