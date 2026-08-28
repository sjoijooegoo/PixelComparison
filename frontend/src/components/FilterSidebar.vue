<script setup>
import { ref, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useRoute, useRouter } from 'vue-router'
import { batchLocation, batchStateFromFilters } from '../batchRoute'
import {
  MAX_DATE_RANGE_DAYS,
  defaultDateRange,
  isDateRangeAllowed,
} from '../store'
import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'

const store = useBatchCatalogStore()
const project = useProjectStore()
const router = useRouter()
const route = useRoute()

const unlistedSceneIds = computed(() => new Set(project.meta.unlisted_scene_ids || []))

function sceneHasBatchData(sceneId) {
  if (store.availableSceneIds === null) return null
  return store.availableSceneIds.includes(sceneId)
}

// 创建时间范围:绑定到 filters.created_from/created_to(YYYY-MM-DD)
const dateRange = computed(() => {
  const { created_from, created_to } = store.filters
  return created_from && created_to ? [created_from, created_to] : undefined
})

// 「指定日期」模式下用于逐个添加的选择器(选完即清空,可继续添加)
const dayPick = ref(null)
const dayPickerOpen = ref(false)
const selectedDateSet = computed(() => new Set(store.filters.created_dates))

function dateToYmd(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function isDaySelected(date) {
  return selectedDateSet.value.has(dateToYmd(date))
}

function contextTarget(overrides = {}, page = 1) {
  return batchLocation(batchStateFromFilters({
    ...store.filters,
    ...overrides,
  }, page, route.query.return_to || ''))
}

function onBranchChange(branchTag) {
  return router.push(contextTarget({ branch_tag: branchTag || 'main' }))
}

function onSceneChange(sceneId) {
  return router.push(contextTarget({ scene_id: sceneId || '' }))
}

function replaceFilters(overrides = {}) {
  return router.replace(contextTarget(overrides))
}

function onDateChange(v) {
  if (v?.[0] && v?.[1]) {
    if (!isDateRangeAllowed(v[0], v[1])) {
      Message.warning(`连续范围最多选择 ${MAX_DATE_RANGE_DAYS} 天；如需跨较长时间，请使用「指定日期」`)
      return
    }
    void replaceFilters({ created_from: v[0], created_to: v[1] })
  } else {
    // 不允许清空成全部时间,恢复默认日期范围(跟随项目设置)
    void replaceFilters(defaultDateRange(project.settings.default_date_range_days))
  }
}

// 切换 范围 / 指定日期 模式
function onModeChange(mode) {
  if (mode !== 'days') dayPickerOpen.value = false
  void replaceFilters({ dateMode: mode })
}

// 切换一个指定日期:未选中则加入,已选中则移除;面板保持展开
function toggleDay(d) {
  if (!d) return
  const set = new Set(store.filters.created_dates)
  if (set.has(d)) set.delete(d)
  else set.add(d)
  dayPick.value = null
  void replaceFilters({ created_dates: [...set].sort() })
}

function onDayPickerVisibleChange(visible) {
  dayPickerOpen.value = visible
}

function removeDay(d) {
  void replaceFilters({
    created_dates: store.filters.created_dates.filter((value) => value !== d),
  })
}

function reset() {
  // 批次管理清空后固定回到 main、全部场景和项目默认日期范围。
  dayPick.value = null
  dayPickerOpen.value = false
  void router.replace(batchLocation(batchStateFromFilters(
    store.defaultFilters(), 1, route.query.return_to || '',
  )))
}
</script>

<template>
  <div class="filter-bar card">
    <div class="field">
      <span class="label">分支</span>
      <a-select :model-value="store.filters.branch_tag" size="small" style="width: 150px"
        @change="onBranchChange">
        <a-option v-for="branch in project.meta.branch_tags" :key="branch" :value="branch">
          {{ branch }}
        </a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">场景ID</span>
      <a-select :model-value="store.filters.scene_id" placeholder="全部场景" allow-clear allow-search
        size="small" style="width: 320px" @change="onSceneChange">
        <a-option v-for="s in project.meta.scene_ids" :key="s" :value="s">
          <span class="scene-option">
            <span class="scene-option-name"
              :class="{ 'is-data-empty': sceneHasBatchData(s) === false }"
              :title="sceneHasBatchData(s) === false ? '当前筛选范围内没有批次数据' : undefined">
              {{ s }}
            </span>
            <span v-if="unlistedSceneIds.has(s)" class="unlisted">未配置</span>
          </span>
        </a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">创建时间</span>
      <a-radio-group :model-value="store.filters.dateMode" type="button" size="small"
        @change="onModeChange">
        <a-radio value="range">范围</a-radio>
        <a-radio value="days">指定日期</a-radio>
      </a-radio-group>
      <template v-if="store.filters.dateMode === 'range'">
        <a-range-picker size="small" style="width: 230px" :allow-clear="false"
          value-format="YYYY-MM-DD" :model-value="dateRange" @change="onDateChange" />
      </template>
      <template v-else>
        <a-date-picker size="small" value-format="YYYY-MM-DD" :model-value="dayPick"
          :popup-visible="dayPickerOpen" :allow-clear="false"
          @popup-visible-change="onDayPickerVisibleChange" @change="toggleDay">
          <a-button size="small" type="secondary">添加日期</a-button>
          <template #cell="{ date }">
            <div class="day-cell" :class="{ selected: isDaySelected(date) }"
              @click.stop="toggleDay(dateToYmd(date))">
              <span class="day-cell-value">{{ date.getDate() }}</span>
            </div>
          </template>
        </a-date-picker>
        <div class="days">
          <a-tag v-for="d in store.filters.created_dates" :key="d" closable size="small"
            color="arcoblue" @close="removeDay(d)">{{ d }}</a-tag>
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
.scene-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.scene-option-name.is-data-empty { color: var(--color-text-4); }
.unlisted { color: var(--color-text-3); font-size: 11px; }
.days { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; max-width: 500px; }
.day-cell {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  user-select: none;
}
.day-cell-value {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  cursor: pointer;
}
.day-cell.selected .day-cell-value {
  color: #fff;
  background: rgb(var(--primary-6));
  font-weight: 600;
}
.spacer { flex: 1; }
</style>
