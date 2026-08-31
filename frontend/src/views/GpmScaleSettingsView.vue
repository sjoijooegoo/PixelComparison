<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'

import { api } from '../api'
import GpmMapLibraryPane from '../components/GpmMapLibraryPane.vue'
import GpmMetricScaleLibraryPane from '../components/GpmMetricScaleLibraryPane.vue'
import GpmScaleBand from '../components/GpmScaleBand.vue'
import GpmScaleSetLibraryPane from '../components/GpmScaleSetLibraryPane.vue'
import { projectedPointStyle } from '../gpmHeatmap/mapConfigPreview'
import {
  compileScaleSegments,
  defaultScaleSegments,
} from '../gpmHeatmap/scaleExpressions'
import { SHADING_QUALITY_OPTIONS } from '../store'
import { useGpmScaleConfigStore } from '../stores/gpmScaleConfigStore'

const store = useGpmScaleConfigStore()

const DEFAULT_PLATFORMS = ['IOS', 'Android', 'Windows']
const QUALITY_LABELS = Object.fromEntries(
  SHADING_QUALITY_OPTIONS.map((option) => [option.value, option.label]),
)

const metricScales = computed(() => store.catalog.metric_scales || [])
const scaleSets = computed(() => store.catalog.scale_sets || [])
const maps = computed(() => store.catalog.maps || [])
const sortedMetricScales = computed(() => [...metricScales.value].sort((a, b) => a.id - b.id))
const sortedScaleSets = computed(() => [...scaleSets.value].sort((a, b) => a.id - b.id))
const scaleOptions = computed(() => metricScales.value.map((scale) => ({
  value: scale.id,
  label: scale.name,
})))
const scaleSetOptions = computed(() => scaleSets.value.map((item) => ({
  value: item.id,
  label: item.name,
})))
const platforms = computed(() => {
  const result = new Set(DEFAULT_PLATFORMS)
  ;(store.catalog.platforms || []).forEach((platform) => result.add(platform))
  maps.value.forEach((map) => (map.bindings || []).forEach((binding) => result.add(binding.platform)))
  const extras = [...result]
    .filter((platform) => !DEFAULT_PLATFORMS.includes(platform))
    .sort((a, b) => a.localeCompare(b))
  return [...DEFAULT_PLATFORMS, ...extras]
})
const qualities = computed(() => SHADING_QUALITY_OPTIONS.map((option) => ({ ...option })))
const platformOptions = computed(() => platforms.value.map((value) => ({ value, label: value })))

function showError(error, fallback) {
  Message.error(error?.message || fallback)
}

function scaleById(id) {
  return metricScales.value.find((scale) => scale.id === id) || null
}

function cloneSegments(scale) {
  const source = Array.isArray(scale?.segments) && scale.segments.length
    ? scale.segments
    : defaultScaleSegments(store.catalog.palette?.colors)
  return source.map((segment, index) => ({
    key: `${Date.now()}-${index}-${Math.random()}`,
    color: segment.color,
    expression: segment.expression,
  }))
}

// 指标标尺编辑器
const scaleEditorOpen = ref(false)
const scaleEditorIntent = ref('create')
const scaleForm = reactive({ id: null, revision: null, name: '', segments: [] })
let draggedSegment = -1

const scaleEditorTitle = computed(() => ({
  create: '新建指标标尺', copy: '复制指标标尺', edit: '编辑指标标尺',
})[scaleEditorIntent.value])

function openScaleEditor(scale = null, intent = 'create') {
  scaleEditorIntent.value = intent
  scaleForm.id = intent === 'edit' ? scale?.id ?? null : null
  scaleForm.revision = intent === 'edit' ? scale?.revision ?? null : null
  scaleForm.name = intent === 'copy' ? `${scale?.name || ''} 副本` : scale?.name || ''
  scaleForm.segments = cloneSegments(scale)
  scaleEditorOpen.value = true
}

function closeScaleEditor() {
  if (!store.saving) scaleEditorOpen.value = false
}

function addSegment() {
  scaleForm.segments.push({
    key: `${Date.now()}-${Math.random()}`,
    color: '#808080',
    expression: '',
  })
}

function removeSegment(index) {
  if (scaleForm.segments.length <= 2) {
    Message.warning('指标标尺至少保留两个颜色段')
    return
  }
  scaleForm.segments.splice(index, 1)
}

function beginSegmentDrag(index) {
  draggedSegment = index
}

function endSegmentDrag() {
  draggedSegment = -1
}

function dropSegment(index) {
  if (draggedSegment < 0 || draggedSegment === index) return
  const [segment] = scaleForm.segments.splice(draggedSegment, 1)
  scaleForm.segments.splice(index, 0, segment)
  draggedSegment = -1
}

async function saveScale() {
  const name = scaleForm.name.trim()
  if (!name) {
    Message.warning('请输入指标标尺名称')
    return
  }
  try {
    const compiled = compileScaleSegments(scaleForm.segments)
    await store.saveMetricScale(scaleForm.id, {
      name, segments: compiled.segments,
      ...(scaleForm.id != null ? { expected_revision: scaleForm.revision } : {}),
    })
    scaleEditorOpen.value = false
    Message.success(scaleForm.id != null ? '指标标尺已更新' : '指标标尺已创建')
  } catch (error) {
    showError(error, '指标标尺保存失败')
  }
}

function deleteScale(scale) {
  Modal.confirm({
    title: `删除“${scale.name}”`,
    content: '删除后无法恢复；被指标标尺集引用时将禁止删除。',
    okText: '删除',
    cancelText: '取消',
    hideCancel: false,
    onOk: async () => {
      try {
        await store.removeMetricScale(scale.id)
        Message.success('指标标尺已删除')
      } catch (error) {
        showError(error, '指标标尺删除失败')
      }
    },
  })
}

// 指标标尺集编辑器
const scaleSetEditorOpen = ref(false)
const scaleSetEditorIntent = ref('create')
const scaleSetForm = reactive({ id: null, revision: null, name: '', items: [] })
let setItemSequence = 0

const scaleSetEditorTitle = computed(() => ({
  create: '新建指标标尺集', copy: '复制指标标尺集', edit: '编辑指标标尺集',
})[scaleSetEditorIntent.value])

function editableSetItems(items) {
  const result = (items || []).map((item) => ({ ...item, key: ++setItemSequence }))
  return result.length ? result : [{ key: ++setItemSequence, metric_key: '', scale_id: null }]
}

function openScaleSetEditor(scaleSet = null, intent = 'create') {
  scaleSetEditorIntent.value = intent
  scaleSetForm.id = intent === 'edit' ? scaleSet?.id ?? null : null
  scaleSetForm.revision = intent === 'edit' ? scaleSet?.revision ?? null : null
  scaleSetForm.name = intent === 'copy' ? `${scaleSet?.name || ''} 副本` : scaleSet?.name || ''
  scaleSetForm.items = editableSetItems(scaleSet?.items)
  scaleSetEditorOpen.value = true
}

function closeScaleSetEditor() {
  if (!store.saving) scaleSetEditorOpen.value = false
}

function addSetItem() {
  scaleSetForm.items.push({ key: ++setItemSequence, metric_key: '', scale_id: null })
}

function removeSetItem(index) {
  scaleSetForm.items.splice(index, 1)
  if (!scaleSetForm.items.length) addSetItem()
}

function validateSetItems() {
  const items = scaleSetForm.items.map((item) => ({
    metric_key: String(item.metric_key || '').trim(),
    scale_id: item.scale_id,
  }))
  for (const [index, item] of items.entries()) {
    if (!item.metric_key || item.scale_id == null) {
      throw new Error(`第 ${index + 1} 行需要同时填写 Key 和指标标尺`)
    }
    if (item.metric_key.length > 200 || /[\u0000-\u001f]/.test(item.metric_key)) {
      throw new Error(`第 ${index + 1} 行 Key 不能包含控制字符且不能超过 200 个字符`)
    }
  }
  if (new Set(items.map((item) => item.metric_key)).size !== items.length) {
    throw new Error('同一指标标尺集内不能配置重复 Key')
  }
  return items
}

async function saveScaleSet() {
  const name = scaleSetForm.name.trim()
  if (!name) {
    Message.warning('请输入指标标尺集名称')
    return
  }
  try {
    const items = validateSetItems()
    await store.saveScaleSet(scaleSetForm.id, {
      name, items,
      ...(scaleSetForm.id != null ? { expected_revision: scaleSetForm.revision } : {}),
    })
    scaleSetEditorOpen.value = false
    Message.success(scaleSetForm.id != null ? '指标标尺集已更新' : '指标标尺集已创建')
  } catch (error) {
    showError(error, '指标标尺集保存失败')
  }
}

function deleteScaleSet(scaleSet) {
  Modal.confirm({
    title: `删除“${scaleSet.name}”`,
    content: '删除后无法恢复；被地图配置引用时将禁止删除。',
    okText: '删除',
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.removeScaleSet(scaleSet.id)
        Message.success('指标标尺集已删除')
      } catch (error) {
        showError(error, '指标标尺集删除失败')
      }
    },
  })
}

function deleteMap(map) {
  Modal.confirm({
    title: `删除“${map.map_name}”`,
    content: '将删除地图图片、坐标配置和标尺绑定；历史批次、点位和截图保留。以后再次上报同名地图时，会重新生成待配置项。',
    okText: '删除',
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.removeMapConfiguration(map.map_name, map.revision)
        Message.success('地图配置已删除')
      } catch (error) {
        showError(error, '地图配置删除失败')
      }
    },
  })
}

// 地图定义、图片、坐标预览与标尺绑定编辑器
const mapEditorOpen = ref(false)
const mapEditorIntent = ref('create')
const selectedMapName = ref('')
const mapImageInput = ref(null)
const mapBindingList = ref(null)
const pendingMapImage = ref(null)
const mapPreview = ref({ source: null, points: [], point_count: 0 })
const mapPreviewLoading = ref(false)
let mapPreviewSequence = 0
let imageInspectionSequence = 0
const mapForm = reactive({
  map_name: '', description: '',
  origin_x: 0, origin_y: 0, range_x: 1, range_y: 1,
  x_reverse: false, y_reverse: true,
  revision: null, bindings: [],
})
let mapBindingSequence = 0
const selectedMap = computed(() => maps.value.find((map) => map.map_name === selectedMapName.value) || null)
const mapEditorTitle = computed(() => (
  mapEditorIntent.value === 'create' ? '新建地图' : `配置地图 · ${mapForm.map_name}`
))
const displayedMapImage = computed(() => pendingMapImage.value || (
  selectedMap.value?.image ? {
    url: selectedMap.value.image.url,
    width: selectedMap.value.image.width,
    height: selectedMap.value.image.height,
  } : null
))
const previewMapDefinition = computed(() => ({
  origin: [Number(mapForm.origin_x), Number(mapForm.origin_y)],
  range: [Number(mapForm.range_x), Number(mapForm.range_y)],
  x_reverse: mapForm.x_reverse,
  y_reverse: mapForm.y_reverse,
}))
const projectedMapPoints = computed(() => (mapPreview.value.points || []).map((point) => ({
  ...point,
  style: projectedPointStyle(previewMapDefinition.value, point.position),
})).filter((point) => point.style?.inBounds))
const coordinateFrameStyle = computed(() => {
  const rangeX = Number(mapForm.range_x)
  const rangeY = Number(mapForm.range_y)
  return rangeX > 0 && rangeY > 0 ? { aspectRatio: `${rangeX} / ${rangeY}` } : {}
})

function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2, useGrouping: false }).format(number)
    : '—'
}

function editableMapBindings(bindings) {
  const scopesBySet = new Map()
  ;(bindings || []).forEach((binding) => {
    const scaleSetId = binding.scale_set_id
    if (!scopesBySet.has(scaleSetId)) scopesBySet.set(scaleSetId, new Map())
    const platformScopes = scopesBySet.get(scaleSetId)
    if (!platformScopes.has(binding.platform)) platformScopes.set(binding.platform, new Set())
    platformScopes.get(binding.platform).add(Number(binding.shading_quality))
  })

  const rows = []
  scopesBySet.forEach((platformScopes, scaleSetId) => {
    const groupsByQualities = new Map()
    platformScopes.forEach((qualitySet, platform) => {
      const shadingQualities = [...qualitySet].sort((a, b) => b - a)
      const signature = shadingQualities.join(',')
      if (!groupsByQualities.has(signature)) {
        groupsByQualities.set(signature, { platforms: [], shading_qualities: shadingQualities })
      }
      groupsByQualities.get(signature).platforms.push(platform)
    })
    groupsByQualities.forEach((group) => rows.push({
      key: ++mapBindingSequence,
      platforms: group.platforms.sort((a, b) => a.localeCompare(b)),
      shading_qualities: group.shading_qualities,
      scale_set_id: scaleSetId,
    }))
  })
  return rows
}

function clearPendingMapImage() {
  imageInspectionSequence += 1
  if (pendingMapImage.value?.url) URL.revokeObjectURL(pendingMapImage.value.url)
  pendingMapImage.value = null
  if (mapImageInput.value) mapImageInput.value.value = ''
}

async function loadMapPreview(mapName) {
  const sequence = ++mapPreviewSequence
  mapPreview.value = { source: null, points: [], point_count: 0 }
  if (!mapName) return
  mapPreviewLoading.value = true
  try {
    const result = await api.gpmMapPreview(mapName)
    if (sequence === mapPreviewSequence) mapPreview.value = result
  } catch (error) {
    if (sequence === mapPreviewSequence) showError(error, '点位预览加载失败')
  } finally {
    if (sequence === mapPreviewSequence) mapPreviewLoading.value = false
  }
}

function openMapEditor(map = null) {
  clearPendingMapImage()
  mapEditorIntent.value = map ? 'edit' : 'create'
  selectedMapName.value = map?.map_name || ''
  Object.assign(mapForm, {
    map_name: map?.map_name || '',
    description: map?.description || '',
    origin_x: map?.origin?.[0] ?? 0,
    origin_y: map?.origin?.[1] ?? 0,
    range_x: map?.range?.[0] ?? 1,
    range_y: map?.range?.[1] ?? 1,
    x_reverse: map?.x_reverse ?? false,
    y_reverse: map?.y_reverse ?? true,
    revision: map?.revision ?? null,
  })
  mapForm.bindings = editableMapBindings(map?.bindings)
  mapEditorOpen.value = true
  if (map) void loadMapPreview(map.map_name)
  else mapPreview.value = { source: null, points: [], point_count: 0 }
}

function closeMapEditor() {
  if (store.saving) return
  mapEditorOpen.value = false
  mapPreviewSequence += 1
  clearPendingMapImage()
}

function inspectMapImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const image = new Image()
    image.onload = () => resolve({
      url, width: image.naturalWidth, height: image.naturalHeight, file,
    })
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('地图图片无法预览'))
    }
    image.src = url
  })
}

async function chooseMapImage(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  clearPendingMapImage()
  const sequence = ++imageInspectionSequence
  try {
    const inspected = await inspectMapImage(file)
    if (sequence !== imageInspectionSequence) {
      URL.revokeObjectURL(inspected.url)
      return
    }
    pendingMapImage.value = inspected
  } catch (error) {
    showError(error, '地图图片无法预览')
  }
}

function addMapBinding() {
  mapForm.bindings.push({
    key: ++mapBindingSequence,
    platforms: [],
    shading_qualities: [],
    scale_set_id: null,
  })
  nextTick(() => {
    if (mapBindingList.value) {
      mapBindingList.value.scrollTop = mapBindingList.value.scrollHeight
    }
  })
}

function removeMapBinding(index) {
  mapForm.bindings.splice(index, 1)
}

function validateMapBindings() {
  const scopes = new Set()
  const bindings = []
  mapForm.bindings.forEach((binding, index) => {
    if (!binding.platforms?.length || !binding.shading_qualities?.length || binding.scale_set_id == null) {
      throw new Error(`第 ${index + 1} 个配置项需要至少选择一个平台、一个画质和一个指标标尺集`)
    }
    binding.platforms.forEach((platform) => {
      binding.shading_qualities.forEach((shadingQuality) => {
        const scope = `${platform}\u0000${shadingQuality}`
        if (scopes.has(scope)) {
          throw new Error(`平台 ${platform} 的${QUALITY_LABELS[shadingQuality] || shadingQuality}画质存在重复配置`)
        }
        scopes.add(scope)
        bindings.push({
          platform,
          shading_quality: Number(shadingQuality),
          scale_set_id: binding.scale_set_id,
        })
      })
    })
  })
  return bindings
}

function validatedMapDefinition() {
  const mapName = mapForm.map_name.trim()
  if (!mapName) throw new Error('请输入地图名称')
  const origin = [Number(mapForm.origin_x), Number(mapForm.origin_y)]
  const range = [Number(mapForm.range_x), Number(mapForm.range_y)]
  if (![...origin, ...range].every(Number.isFinite)) throw new Error('坐标起点和范围必须是有效数字')
  if (range.some((value) => value <= 0)) throw new Error('坐标范围必须大于 0')
  return {
    map_name: mapName,
    description: mapForm.description.trim() || mapName,
    origin,
    range,
    x_reverse: mapForm.x_reverse,
    y_reverse: mapForm.y_reverse,
    ...(mapEditorIntent.value === 'edit'
      ? { expected_revision: mapForm.revision } : {}),
  }
}

async function saveMapConfiguration() {
  try {
    const definition = validatedMapDefinition()
    const bindings = validateMapBindings()
    await store.saveMapConfiguration({
      mapName: definition.map_name,
      configuration: { ...definition, bindings },
      image: pendingMapImage.value?.file || null,
    })
    mapEditorOpen.value = false
    clearPendingMapImage()
    Message.success(mapEditorIntent.value === 'create' ? '地图已创建' : '地图配置已保存')
  } catch (error) {
    showError(error, '地图配置保存失败')
  }
}

onMounted(async () => {
  try {
    await store.load()
  } catch {
    // 使用页内错误和重试入口。
  }
})
onBeforeUnmount(() => {
  mapPreviewSequence += 1
  clearPendingMapImage()
})

</script>

<template>
  <main class="scale-settings-page app-body">
    <section class="scale-workspace card">
      <div v-if="store.error && !metricScales.length && !scaleSets.length" class="load-error">
        <span>{{ store.error }}</span>
        <a-button size="small" type="primary" @click="store.load().catch(() => {})">
          重新加载
        </a-button>
      </div>

      <div v-else class="library-layout">
        <GpmMapLibraryPane :maps="maps" @create="openMapEditor()" @edit="openMapEditor"
          @delete="deleteMap" />
        <GpmScaleSetLibraryPane :items="sortedScaleSets" :can-create="Boolean(metricScales.length)"
          @create="openScaleSetEditor()" @copy="openScaleSetEditor($event, 'copy')"
          @edit="openScaleSetEditor($event, 'edit')" @delete="deleteScaleSet" />
        <GpmMetricScaleLibraryPane :items="sortedMetricScales" @create="openScaleEditor()"
          @copy="openScaleEditor($event, 'copy')" @edit="openScaleEditor($event, 'edit')"
          @delete="deleteScale" />
      </div>
    </section>

    <a-modal :visible="scaleEditorOpen" :footer="false" :closable="!store.saving"
      :mask-closable="!store.saving" width="840px" modal-class="gpm-editor-modal"
      @cancel="closeScaleEditor">
      <template #title>{{ scaleEditorTitle }}</template>
      <div class="modal-editor-body contained-list-editor-body">
        <label class="field-label">名称</label>
        <a-input v-model="scaleForm.name" :max-length="100" placeholder="输入标尺名称" />

        <div class="editor-section-title">
          <strong>颜色分段</strong>
          <a-button size="mini" type="text" :disabled="scaleForm.segments.length >= 10" @click="addSegment">
            添加颜色段
          </a-button>
        </div>
        <div class="segment-list">
          <div v-for="(segment, index) in scaleForm.segments" :key="segment.key"
            class="segment-row" @dragover.prevent @drop="dropSegment(index)">
            <span class="drag-handle" title="拖拽调整顺序" draggable="true"
              @dragstart.stop="beginSegmentDrag(index)" @dragend="endSegmentDrag">⋮⋮</span>
            <input v-model="segment.color" type="color" class="color-picker" aria-label="颜色">
            <a-input v-model="segment.color" class="color-text" size="small" />
            <a-input v-model="segment.expression" class="expression-input" size="small"
              placeholder="例如 >=365 & <390" />
            <a-button size="mini" type="text" status="danger" @click="removeSegment(index)">删除</a-button>
          </div>
        </div>
      </div>
      <footer class="modal-editor-footer">
        <a-button size="small" :disabled="store.saving" @click="closeScaleEditor">取消</a-button>
        <a-button size="small" type="primary" :loading="store.saving" @click="saveScale">保存标尺</a-button>
      </footer>
    </a-modal>

    <a-modal :visible="scaleSetEditorOpen" :footer="false" :closable="!store.saving"
      :mask-closable="!store.saving" width="820px" modal-class="gpm-editor-modal"
      @cancel="closeScaleSetEditor">
      <template #title>{{ scaleSetEditorTitle }}</template>
      <div class="modal-editor-body contained-list-editor-body">
        <label class="field-label">名称</label>
        <a-input v-model="scaleSetForm.name" :max-length="100" placeholder="输入标尺集名称" />

        <div class="editor-section-title">
          <strong>Key 与指标标尺</strong>
          <a-button size="mini" type="text" @click="addSetItem">添加 Key</a-button>
        </div>
        <div class="set-item-head"><span>上报 Key</span><span>指标标尺</span><span>颜色段</span><span></span></div>
        <div class="set-item-list">
          <div v-for="(item, index) in scaleSetForm.items" :key="item.key" class="set-item-row">
            <a-input v-model="item.metric_key" size="small" placeholder="例如 Character_DC" />
            <a-select v-model="item.scale_id" :options="scaleOptions" allow-search
              size="small" placeholder="选择指标标尺" />
            <GpmScaleBand v-if="scaleById(item.scale_id)" class="set-scale-preview"
              :segments="scaleById(item.scale_id).segments" compact />
            <span v-else class="preview-placeholder">—</span>
            <a-button size="mini" type="text" status="danger" @click="removeSetItem(index)">删除</a-button>
          </div>
        </div>
      </div>
      <footer class="modal-editor-footer">
        <a-button size="small" :disabled="store.saving" @click="closeScaleSetEditor">取消</a-button>
        <a-button size="small" type="primary" :loading="store.saving" @click="saveScaleSet">保存标尺集</a-button>
      </footer>
    </a-modal>

    <a-modal :visible="mapEditorOpen" :footer="false" :closable="!store.saving"
      :mask-closable="!store.saving" width="1180px" modal-class="gpm-editor-modal map-config-modal"
      @cancel="closeMapEditor">
      <template #title>{{ mapEditorTitle }}</template>
      <div class="modal-editor-body map-config-editor">
        <section class="map-definition-editor editor-panel">
          <header><strong>基础与坐标</strong></header>
          <div class="map-fields">
            <label class="map-field map-name-field">
              <span>地图名称</span>
              <a-input v-model="mapForm.map_name" size="small" :disabled="mapEditorIntent === 'edit'"
                placeholder="必须与上报 map_name 一致" />
            </label>
            <label class="map-field description-field">
              <span>描述</span>
              <a-input v-model="mapForm.description" size="small" placeholder="可选" />
            </label>
            <label class="map-field"><span>起点 X</span><a-input-number v-model="mapForm.origin_x" size="small" /></label>
            <label class="map-field"><span>起点 Y</span><a-input-number v-model="mapForm.origin_y" size="small" /></label>
            <label class="map-field"><span>范围 X</span><a-input-number v-model="mapForm.range_x" size="small" :min="0.000001" /></label>
            <label class="map-field"><span>范围 Y</span><a-input-number v-model="mapForm.range_y" size="small" :min="0.000001" /></label>
            <label class="axis-toggle"><a-switch v-model="mapForm.x_reverse" size="small" />反转 X 轴</label>
            <label class="axis-toggle"><a-switch v-model="mapForm.y_reverse" size="small" />反转 Y 轴</label>
          </div>
        </section>

        <div class="map-config-columns">
          <section class="map-preview-editor editor-panel">
            <header>
              <strong>地图图片与点位预览</strong>
              <div>
                <input ref="mapImageInput" type="file" accept="image/png,image/jpeg,image/webp"
                  hidden @change="chooseMapImage">
                <a-button v-if="pendingMapImage" size="mini" type="text" @click="clearPendingMapImage">取消替换</a-button>
                <a-button size="mini" type="text" @click="mapImageInput?.click()">
                  {{ displayedMapImage ? '替换图片' : '选择图片' }}
                </a-button>
              </div>
            </header>
            <div class="map-preview-stage">
              <div v-if="displayedMapImage" class="map-coordinate-frame" :style="coordinateFrameStyle">
                <img :src="displayedMapImage.url" alt="地图坐标匹配预览">
                <span v-for="point in projectedMapPoints" :key="point.id" class="map-preview-point"
                  :style="point.style" :title="`点位 ${point.index}`"></span>
              </div>
              <button v-else type="button" class="map-image-empty" @click="mapImageInput?.click()">
                <strong>选择地图图片</strong><span>PNG、JPEG 或 WebP，最大 32 MiB</span>
              </button>
            </div>
            <footer class="map-preview-facts">
              <span>图片 {{ displayedMapImage ? `${displayedMapImage.width} × ${displayedMapImage.height}` : '未上传' }}</span>
              <span>坐标 {{ formatNumber(mapForm.range_x) }} × {{ formatNumber(mapForm.range_y) }}</span>
              <span v-if="mapPreviewLoading">读取点位中…</span>
              <span v-else>{{ projectedMapPoints.length }} / {{ mapPreview.point_count }} 个点位在范围内</span>
            </footer>
          </section>

          <section class="map-binding-editor editor-panel">
            <div class="map-binding-toolbar">
              <strong>平台、画质与指标标尺集</strong>
              <a-button size="mini" type="text" :disabled="!scaleSets.length" @click="addMapBinding">
                添加配置项
              </a-button>
            </div>
            <div v-if="mapForm.bindings.length" class="map-binding-head">
              <span>平台</span><span>画质</span><span>指标标尺集</span><span></span>
            </div>
            <div v-if="mapForm.bindings.length" ref="mapBindingList" class="map-binding-list">
              <div v-for="(binding, index) in mapForm.bindings" :key="binding.key" class="map-binding-row">
                <a-select v-model="binding.platforms" :options="platformOptions" multiple allow-search
                  size="small" placeholder="选择平台" />
                <a-select v-model="binding.shading_qualities" :options="qualities" multiple
                  size="small" placeholder="选择画质" />
                <a-select v-model="binding.scale_set_id" :options="scaleSetOptions" allow-search
                  size="small" placeholder="选择指标标尺集" />
                <a-button size="mini" type="text" status="danger" @click="removeMapBinding(index)">删除</a-button>
              </div>
            </div>
            <div v-else class="map-binding-empty">
              暂无配置，热力图将使用动态线性着色
            </div>
          </section>
        </div>
      </div>
      <footer class="modal-editor-footer">
        <a-button size="small" :disabled="store.saving" @click="closeMapEditor">取消</a-button>
        <a-button size="small" type="primary" :loading="store.saving" @click="saveMapConfiguration">
          {{ mapEditorIntent === 'create' ? '创建地图' : '保存配置' }}
        </a-button>
      </footer>
    </a-modal>
  </main>
</template>

<style scoped>
.scale-settings-page { min-width: 1240px; flex-direction: column; }
.scale-workspace { flex: 1; min-height: 0; padding: 0; overflow: hidden; }
.load-error { min-height: 180px; display: flex; align-items: center; justify-content: center; gap: 12px; color: rgb(var(--red-6)); }
.library-layout {
  height: 100%; min-height: 0; display: grid;
  grid-template-columns: minmax(500px, 1.16fr) minmax(250px, .55fr) minmax(490px, 1.08fr);
}
.library-pane + .library-pane { border-left: 1px solid var(--color-border-1); }

.modal-editor-body { max-height: min(68vh, 650px); padding: 2px 2px 12px; overflow: auto; }
.field-label { display: block; margin: 0 0 6px; color: var(--color-text-3); font-size: 11px; }
.editor-section-title { margin: 18px 0 8px; display: flex; align-items: center; justify-content: space-between; }
.editor-section-title strong { color: var(--color-text-2); font-size: 12px; }
.segment-list, .set-item-list { display: grid; gap: 6px; }
.segment-row {
  min-height: 42px; padding: 5px 7px; display: grid;
  grid-template-columns: 22px 28px 92px minmax(230px, 1fr) 48px; align-items: center; gap: 8px;
  border: 1px solid var(--color-border-1); border-radius: 4px; background: var(--color-fill-1);
}
.drag-handle { color: var(--color-text-4); text-align: center; cursor: grab; user-select: none; }
.drag-handle:active { cursor: grabbing; }
.color-picker { width: 28px; height: 26px; padding: 0; border: 0; border-radius: 3px; background: transparent; cursor: pointer; }
.color-text :deep(input), .expression-input :deep(input) { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.modal-editor-footer { padding-top: 12px; border-top: 1px solid var(--color-border-1); display: flex; justify-content: flex-end; gap: 8px; }
.set-item-head, .set-item-row {
  display: grid; grid-template-columns: minmax(200px, 1fr) minmax(190px, 1fr) 120px 48px;
  align-items: center; gap: 8px;
}
.set-item-head { padding: 0 8px 4px; color: var(--color-text-4); font-size: 10px; }
.contained-list-editor-body { max-height: none; overflow: hidden; }
.contained-list-editor-body .segment-list,
.contained-list-editor-body .set-item-list {
  max-height: min(42vh, 420px); padding-right: 4px; overflow-x: hidden; overflow-y: auto;
  overscroll-behavior: contain; scrollbar-gutter: stable; align-content: start;
}
.set-item-row { min-height: 42px; padding: 5px 7px; border: 1px solid var(--color-border-1); border-radius: 4px; background: var(--color-fill-1); }
.set-scale-preview { width: 112px; }
.preview-placeholder { color: var(--color-text-4); text-align: center; }
.map-binding-toolbar {
  margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;
}
.map-binding-toolbar strong { color: var(--color-text-2); font-size: 12px; }
.map-binding-head,
.map-binding-row {
  display: grid; grid-template-columns: 170px 132px minmax(180px, 1fr) 44px;
  align-items: center; gap: 8px;
}
.map-binding-head { padding: 0 8px 5px; color: var(--color-text-4); font-size: 10px; }
.map-binding-list {
  flex: 1; min-height: 0; padding-right: 3px; display: flex; flex-direction: column; gap: 6px;
  overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable;
}
.map-binding-row {
  flex: 0 0 auto; min-height: 44px; height: auto; padding: 6px 7px;
  align-items: start; border: 1px solid var(--color-border-1);
  border-radius: 4px; background: var(--color-fill-1);
}
.map-binding-row :deep(.arco-select-view) { min-width: 0; }
.map-binding-row :deep(.arco-select-view-multiple) { height: auto; min-height: 28px; }
.map-binding-row :deep(.arco-select-view-multiple .arco-select-view-inner) {
  display: flex; flex-wrap: wrap; align-items: center;
}
.map-binding-row :deep(.arco-tag) { white-space: nowrap; }
.map-binding-row :deep(.arco-btn) { align-self: center; }
.map-binding-empty {
  flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center;
  border: 1px dashed var(--color-border-2); border-radius: 4px;
  color: var(--color-text-4); font-size: 12px;
}
.map-config-editor { display: grid; gap: 10px; }
.map-config-editor .editor-panel {
  min-width: 0; border: 1px solid var(--color-border-1); border-radius: 5px;
  background: color-mix(in srgb, var(--color-fill-1) 62%, transparent);
}
.map-config-editor .editor-panel > header {
  min-height: 34px; padding: 6px 10px; display: flex; align-items: center;
  justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--color-border-1);
}
.map-config-editor .editor-panel > header strong { color: var(--color-text-2); font-size: 11px; }
.map-config-editor .editor-panel > header > div { display: flex; align-items: center; gap: 5px; }
.map-definition-editor { padding-bottom: 10px; }
.map-fields {
  padding: 10px; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
  align-items: end; gap: 9px;
}
.map-field { min-width: 0; display: grid; gap: 5px; }
.map-field > span { color: var(--color-text-4); font-size: 10px; }
.map-name-field { grid-column: span 3; }
.description-field { grid-column: span 3; }
.map-field :deep(.arco-input-number) { width: 100%; }
.axis-toggle {
  min-height: 28px; display: flex; align-items: center; justify-content: center; gap: 6px;
  color: var(--color-text-3); font-size: 10px;
}
.map-config-columns {
  height: 330px; min-height: 0; display: grid;
  grid-template-columns: minmax(400px, .9fr) minmax(0, 1.18fr);
  gap: 10px;
}
.map-preview-editor { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.map-preview-stage {
  flex: 1; min-height: 0; padding: 14px; display: grid; place-items: center;
  overflow: hidden; background: var(--color-bg-2);
}
.map-coordinate-frame {
  position: relative; max-width: 100%; max-height: 260px; height: 100%; width: auto;
  border: 1px solid var(--color-border-2); background: var(--color-fill-1);
}
.map-coordinate-frame img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; }
.map-preview-point {
  position: absolute; z-index: 1; width: 6px; height: 6px; transform: translate(-50%, -50%);
  border-radius: 1px; background: rgb(var(--arcoblue-5)); box-shadow: 0 0 0 1px rgba(0, 0, 0, .72);
}
.map-image-empty {
  width: 100%; height: 100%; min-height: 220px; border: 1px dashed var(--color-border-2);
  border-radius: 4px; display: grid; place-content: center; gap: 5px;
  background: transparent; color: var(--color-text-3); cursor: pointer; font: inherit;
}
.map-image-empty:hover { border-color: rgba(var(--arcoblue-5), .55); background: var(--color-fill-1); }
.map-image-empty strong { font-size: 12px; }
.map-image-empty span { color: var(--color-text-4); font-size: 10px; }
.map-preview-facts {
  min-height: 34px; padding: 6px 10px; display: flex; align-items: center;
  justify-content: space-between; gap: 8px; border-top: 1px solid var(--color-border-1);
  color: var(--color-text-4); font-size: 9px; font-variant-numeric: tabular-nums;
}
.map-binding-editor {
  min-height: 0; padding: 9px; display: flex; flex-direction: column; overflow: hidden;
}
.map-binding-editor .map-binding-toolbar { min-height: 24px; margin-bottom: 7px; }
.map-config-modal .modal-editor-body { max-height: min(72vh, 720px); }
</style>
