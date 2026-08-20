<script setup>
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useRouter } from 'vue-router'

import {
  MAX_DATE_RANGE_DAYS,
  defaultDateRange,
  isDateRangeAllowed,
  visibleQualityOptions,
} from '../store'
import { screenshotLocation, screenshotStateFromFilters } from '../screenshotRoute'
import { useProjectStore } from '../stores/projectStore'
import { useScreenshotComparisonStore } from '../stores/screenshotComparisonStore'

const project = useProjectStore()
const store = useScreenshotComparisonStore()
const router = useRouter()
const qualityOptions = computed(() => visibleQualityOptions(project.settings))
const unlistedSceneIds = computed(() => new Set(project.meta.unlisted_scene_ids || []))
const dateRange = computed(() => {
  const { created_from: from, created_to: to } = store.filters
  return from && to ? [from, to] : undefined
})
const dayPick = ref(null)
const dayPickerOpen = ref(false)
const selectedDateSet = computed(() => new Set(store.filters.created_dates))

function sceneHasScreenshotData(sceneId) {
  if (store.availableSceneIds === null) return null
  return store.availableSceneIds.includes(sceneId)
}

function dateToYmd(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function isDaySelected(date) {
  return selectedDateSet.value.has(dateToYmd(date))
}

function contextTarget(overrides = {}) {
  return screenshotLocation(screenshotStateFromFilters({
    ...store.filters,
    ...overrides,
  }))
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

function onQualityChange(quality) {
  void replaceFilters({ shading_quality: quality ?? '' })
}

function onDateChange(value) {
  if (value?.[0] && value?.[1]) {
    if (!isDateRangeAllowed(value[0], value[1])) {
      Message.warning(`连续范围最多选择 ${MAX_DATE_RANGE_DAYS} 天；如需跨较长时间，请使用「指定日期」`)
      return
    }
    void replaceFilters({ created_from: value[0], created_to: value[1] })
  } else {
    void replaceFilters(defaultDateRange(project.settings.default_date_range_days))
  }
}

function onModeChange(mode) {
  if (mode !== 'days') dayPickerOpen.value = false
  void replaceFilters({ dateMode: mode })
}

function toggleDay(day) {
  if (!day) return
  const selected = new Set(store.filters.created_dates)
  if (selected.has(day)) selected.delete(day)
  else selected.add(day)
  dayPick.value = null
  void replaceFilters({ created_dates: [...selected].sort() })
}

function removeDay(day) {
  void replaceFilters({
    created_dates: store.filters.created_dates.filter((value) => value !== day),
  })
}

function reset() {
  dayPick.value = null
  dayPickerOpen.value = false
  void router.replace(screenshotLocation(screenshotStateFromFilters(
    store.defaultFilters(store.filters.branch_tag, store.filters.scene_id),
  )))
}
</script>

<template>
  <div class="filter-bar card">
    <div class="field">
      <span class="label">分支</span>
      <a-select :model-value="store.filters.branch_tag" size="small" style="width: 150px"
        @change="onBranchChange">
        <a-option v-for="branch in project.meta.branch_tags" :key="branch" :value="branch">{{ branch }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">场景ID</span>
      <a-select :model-value="store.filters.scene_id" placeholder="请选择场景" allow-clear allow-search
        size="small" style="width: 320px" @change="onSceneChange">
        <a-option v-for="scene in project.meta.scene_ids" :key="scene" :value="scene">
          <span class="scene-option">
            <span class="scene-option-name"
              :class="{ 'is-data-empty': sceneHasScreenshotData(scene) === false }"
              :title="sceneHasScreenshotData(scene) === false ? '当前筛选范围内没有完整截图' : undefined">
              {{ scene }}
            </span>
            <span v-if="unlistedSceneIds.has(scene)" class="unlisted">未配置</span>
          </span>
        </a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">画质</span>
      <a-select :model-value="store.filters.shading_quality" placeholder="全部画质" allow-clear size="small"
        style="width: 130px" @change="onQualityChange">
        <a-option v-for="option in qualityOptions" :key="option.value" :value="option.value">{{ option.label }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">创建时间</span>
      <a-radio-group :model-value="store.filters.dateMode" type="button" size="small"
        @change="onModeChange">
        <a-radio value="range">范围</a-radio>
        <a-radio value="days">指定日期</a-radio>
      </a-radio-group>
      <a-range-picker v-if="store.filters.dateMode === 'range'" size="small" style="width: 230px"
        :allow-clear="false" value-format="YYYY-MM-DD" :model-value="dateRange" @change="onDateChange" />
      <template v-else>
        <a-date-picker size="small" value-format="YYYY-MM-DD" :model-value="dayPick"
          :popup-visible="dayPickerOpen" :allow-clear="false"
          @popup-visible-change="dayPickerOpen = $event" @change="toggleDay">
          <a-button size="small" type="secondary">添加日期</a-button>
          <template #cell="{ date }">
            <div class="day-cell" :class="{ selected: isDaySelected(date) }"
              @click.stop="toggleDay(dateToYmd(date))">
              <span class="day-cell-value">{{ date.getDate() }}</span>
            </div>
          </template>
        </a-date-picker>
        <div class="days">
          <a-tag v-for="day in store.filters.created_dates" :key="day" closable size="small"
            color="arcoblue" @close="removeDay(day)">{{ day }}</a-tag>
        </div>
      </template>
    </div>
    <div class="spacer"></div>
    <a-button size="small" @click="reset">清空</a-button>
  </div>
</template>

<style scoped>
.filter-bar { flex: 0 0 auto; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; padding: 10px 14px; }
.field { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.field .label { color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.scene-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.scene-option-name.is-data-empty { color: var(--color-text-4); }
.unlisted { color: var(--color-text-3); font-size: 11px; }
.days { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; max-width: 500px; }
.day-cell { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; cursor: pointer; user-select: none; }
.day-cell-value { width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; }
.day-cell.selected .day-cell-value { color: #fff; background: rgb(var(--primary-6)); font-weight: 600; }
.spacer { flex: 1; }
</style>
