<script setup>
import { ref, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  MAX_DATE_RANGE_DAYS,
  defaultDateRange,
  isDateRangeAllowed,
  visibleQualityOptions,
} from '../store'
import { useBatchCatalogStore } from '../stores/batchCatalogStore'
import { useProjectStore } from '../stores/projectStore'

const store = useBatchCatalogStore()
const project = useProjectStore()

// 画质下拉选项:跟随项目设置「筛选框显示的画质」
const qualityOptions = computed(() => visibleQualityOptions(project.settings))
const unlistedSceneIds = computed(() => new Set(project.meta.unlisted_scene_ids || []))

function sceneHasBatchData(sceneId) {
  const flagsByBranch = project.meta.scene_data_flags
  const branchTag = store.filters.branch_tag || 'main'
  if (!flagsByBranch || !Object.prototype.hasOwnProperty.call(flagsByBranch, branchTag)) {
    return null
  }
  return Object.prototype.hasOwnProperty.call(flagsByBranch[branchTag] || {}, sceneId)
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

// 任意筛选项变更即自动应用(静默)
async function applyNow() {
  try {
    await store.applyFilters()
  } catch (error) {
    Message.error(error?.message || '筛选数据加载失败，请重试')
  }
}

async function onBranchChange(value) {
  try {
    await store.changeBranch(value)
  } catch (error) {
    Message.error(error?.message || '分支数据加载失败，请重试')
  }
}

function onDateChange(v) {
  if (v?.[0] && v?.[1]) {
    if (!isDateRangeAllowed(v[0], v[1])) {
      Message.warning(`连续范围最多选择 ${MAX_DATE_RANGE_DAYS} 天；如需跨较长时间，请使用「指定日期」`)
      return
    }
    store.filters.created_from = v[0]
    store.filters.created_to = v[1]
  } else {
    // 不允许清空成全部时间,恢复默认日期范围(跟随项目设置)
    Object.assign(store.filters, defaultDateRange(project.settings.default_date_range_days))
  }
  applyNow()
}

// 切换 范围 / 指定日期 模式
function onModeChange() {
  if (store.filters.dateMode !== 'days') {
    dayPickerOpen.value = false
  }
  applyNow()
}

// 切换一个指定日期:未选中则加入,已选中则移除;面板保持展开
function toggleDay(d) {
  if (!d) return
  const set = new Set(store.filters.created_dates)
  if (set.has(d)) set.delete(d)
  else set.add(d)
  store.filters.created_dates = [...set].sort()
  dayPick.value = null
  applyNow()
}

function onDayPickerVisibleChange(visible) {
  dayPickerOpen.value = visible
}

function removeDay(d) {
  store.filters.created_dates = store.filters.created_dates.filter((x) => x !== d)
  applyNow()
}

async function reset() {
  // 恢复到项目设置里的默认筛选(默认画质 + 默认日期范围);不放出全部时间数据
  dayPick.value = null
  dayPickerOpen.value = false
  try {
    await store.resetFilters()
  } catch (error) {
    Message.error(error?.message || '筛选数据加载失败，请重试')
  }
}
</script>

<template>
  <div class="filter-bar card">
    <div class="field">
      <span class="label">分支</span>
      <a-select v-model="store.filters.branch_tag" size="small" style="width: 150px"
        @change="onBranchChange">
        <a-option v-for="branch in project.meta.branch_tags" :key="branch" :value="branch">
          {{ branch }}
        </a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">场景ID</span>
      <a-select v-model="store.filters.scene_id" placeholder="全部场景" allow-clear allow-search size="small"
        style="width: 320px" @change="applyNow">
        <a-option v-for="s in project.meta.scene_ids" :key="s" :value="s">
          <span class="scene-option">
            <span class="scene-option-name"
              :class="{ 'is-data-empty': sceneHasBatchData(s) === false }"
              :title="sceneHasBatchData(s) === false ? '当前分支没有批次数据' : undefined">
              {{ s }}
            </span>
            <span v-if="unlistedSceneIds.has(s)" class="unlisted">未配置</span>
          </span>
        </a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">画质</span>
      <a-select v-model="store.filters.shading_quality" placeholder="全部画质" allow-clear size="small"
        style="width: 130px" @change="applyNow">
        <a-option v-for="o in qualityOptions" :key="o.value" :value="o.value">{{ o.label }}</a-option>
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
