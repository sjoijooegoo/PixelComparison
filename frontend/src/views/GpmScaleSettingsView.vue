<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'

import GpmScaleBand from '../components/GpmScaleBand.vue'
import GpmSettingsNav from '../components/GpmSettingsNav.vue'
import {
  compileScaleSegments,
  defaultScaleSegments,
  segmentsFromLegacy,
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
const sortedMetricScales = computed(() => [...metricScales.value].sort((a, b) => b.id - a.id))
const sortedScaleSets = computed(() => [...scaleSets.value].sort((a, b) => b.id - a.id))
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
    : scale
      ? segmentsFromLegacy(scale.thresholds, scale.colors, scale.direction)
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
      ...(scaleForm.id ? { expected_revision: scaleForm.revision } : {}),
    })
    scaleEditorOpen.value = false
    Message.success(scaleForm.id ? '指标标尺已更新' : '指标标尺已创建')
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
      ...(scaleSetForm.id ? { expected_revision: scaleSetForm.revision } : {}),
    })
    scaleSetEditorOpen.value = false
    Message.success(scaleSetForm.id ? '指标标尺集已更新' : '指标标尺集已创建')
  } catch (error) {
    showError(error, '指标标尺集保存失败')
  }
}

function deleteScaleSet(scaleSet) {
  Modal.confirm({
    title: `删除“${scaleSet.name}”`,
    content: '删除后无法恢复；被地图应用引用时将禁止删除。',
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

// 地图作用域绑定编辑器
const mapEditorOpen = ref(false)
const selectedMapName = ref('')
const mapSearch = ref('')
const mapForm = reactive({ map_name: '', revision: '', bindings: [] })
let mapBindingSequence = 0
const filteredMaps = computed(() => {
  const query = mapSearch.value.trim().toLocaleLowerCase()
  return maps.value.filter((map) => !query || `${map.map_name} ${map.map_id}`.toLocaleLowerCase().includes(query))
})
const selectedMap = computed(() => maps.value.find((map) => map.map_name === selectedMapName.value) || null)

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

function openMapEditor(map) {
  selectedMapName.value = map.map_name
  mapForm.map_name = map.map_name
  mapForm.revision = map.binding_revision || ''
  mapForm.bindings = editableMapBindings(map.bindings)
  mapEditorOpen.value = true
}

function closeMapEditor() {
  if (!store.saving) mapEditorOpen.value = false
}

function addMapBinding() {
  mapForm.bindings.push({
    key: ++mapBindingSequence,
    platforms: [],
    shading_qualities: [],
    scale_set_id: null,
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

async function saveMapBindings() {
  if (!mapForm.map_name) return
  try {
    const bindings = validateMapBindings()
    await store.saveMapBindings(mapForm.map_name, {
      bindings,
      expected_revision: mapForm.revision,
    })
    mapEditorOpen.value = false
    Message.success('地图应用已保存')
  } catch (error) {
    showError(error, '地图应用保存失败')
  }
}

onMounted(async () => {
  try {
    await store.load()
  } catch {
    // 使用页内错误和重试入口。
  }
})
</script>

<template>
  <main class="scale-settings-page app-body">
    <GpmSettingsNav />

    <section class="scale-workspace card">
      <div v-if="store.error && !metricScales.length && !scaleSets.length" class="load-error">
        <span>{{ store.error }}</span>
        <a-button size="small" type="primary" @click="store.load().catch(() => {})">
          重新加载
        </a-button>
      </div>

      <div v-else class="library-layout">
        <section class="library-pane scale-pane">
          <header class="section-toolbar">
            <div>
              <h3>指标标尺库</h3>
              <span>{{ metricScales.length }} 个</span>
            </div>
            <a-button type="primary" size="small" @click="openScaleEditor()">新建标尺</a-button>
          </header>
          <div class="data-table-shell library-table-scroll">
            <table class="library-table scale-library-table">
              <thead><tr><th>ID</th><th>名称</th><th>颜色段</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="scale in sortedMetricScales" :key="scale.id">
                  <td class="numeric-cell">{{ scale.id }}</td>
                  <td><strong :title="scale.name">{{ scale.name }}</strong></td>
                  <td>
                    <GpmScaleBand class="scale-preview" :thresholds="scale.thresholds"
                      :colors="scale.colors" :direction="scale.direction" compact />
                  </td>
                  <td class="action-cell compact-actions">
                    <a-button size="mini" type="text" @click="openScaleEditor(scale, 'copy')">复制</a-button>
                    <a-button size="mini" type="text" @click="openScaleEditor(scale, 'edit')">编辑</a-button>
                    <a-button size="mini" type="text" status="danger" @click="deleteScale(scale)">删除</a-button>
                  </td>
                </tr>
                <tr v-if="!sortedMetricScales.length"><td colspan="4" class="empty-cell">暂无指标标尺</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="library-pane set-pane">
          <header class="section-toolbar">
            <div>
              <h3>指标标尺集</h3>
              <span>{{ scaleSets.length }} 个</span>
            </div>
            <a-button type="primary" size="small" :disabled="!metricScales.length"
              @click="openScaleSetEditor()">新建标尺集</a-button>
          </header>
          <div class="data-table-shell library-table-scroll">
            <table class="library-table set-library-table">
              <thead><tr><th>ID</th><th>名称</th><th>应用</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="scaleSet in sortedScaleSets" :key="scaleSet.id">
                  <td class="numeric-cell">{{ scaleSet.id }}</td>
                  <td><strong :title="scaleSet.name">{{ scaleSet.name }}</strong></td>
                  <td class="numeric-cell">{{ scaleSet.bindings?.length || 0 }}</td>
                  <td class="action-cell compact-actions">
                    <a-button size="mini" type="text" @click="openScaleSetEditor(scaleSet, 'copy')">复制</a-button>
                    <a-button size="mini" type="text" @click="openScaleSetEditor(scaleSet, 'edit')">编辑</a-button>
                    <a-button size="mini" type="text" status="danger" @click="deleteScaleSet(scaleSet)">删除</a-button>
                  </td>
                </tr>
                <tr v-if="!sortedScaleSets.length"><td colspan="4" class="empty-cell">暂无指标标尺集</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="library-pane map-pane">
          <header class="section-toolbar map-list-toolbar">
            <div>
              <h3>地图应用</h3>
              <span>{{ maps.length }} 张地图</span>
            </div>
            <a-input v-model="mapSearch" class="map-search" size="small" allow-clear placeholder="搜索地图" />
          </header>
          <div class="data-table-shell library-table-scroll">
            <table class="library-table map-library-table">
              <thead><tr><th>地图名称</th><th>配置状态</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="map in filteredMaps" :key="map.map_name">
                  <td><strong :title="map.map_name">{{ map.map_name }}</strong></td>
                  <td>
                    <span class="config-status" :class="{ configured: map.bindings?.length }">
                      {{ map.bindings?.length ? '已配置' : '未配置' }}
                    </span>
                  </td>
                  <td class="action-cell">
                    <a-button size="mini" type="text" @click="openMapEditor(map)">配置</a-button>
                  </td>
                </tr>
                <tr v-if="!filteredMaps.length"><td colspan="3" class="empty-cell">暂无地图</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>

    <a-modal :visible="scaleEditorOpen" :footer="false" :closable="!store.saving"
      :mask-closable="false" width="840px" modal-class="gpm-editor-modal"
      @cancel="closeScaleEditor">
      <template #title>{{ scaleEditorTitle }}</template>
      <div class="modal-editor-body">
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
            class="segment-row" draggable="true" @dragstart="beginSegmentDrag(index)"
            @dragover.prevent @drop="dropSegment(index)">
            <span class="drag-handle" title="拖拽调整顺序">⋮⋮</span>
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
      :mask-closable="false" width="820px" modal-class="gpm-editor-modal"
      @cancel="closeScaleSetEditor">
      <template #title>{{ scaleSetEditorTitle }}</template>
      <div class="modal-editor-body">
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
              :thresholds="scaleById(item.scale_id).thresholds"
              :colors="scaleById(item.scale_id).colors"
              :direction="scaleById(item.scale_id).direction" compact />
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
      :mask-closable="false" width="760px" modal-class="gpm-editor-modal"
      @cancel="closeMapEditor">
      <template #title>配置地图 · {{ selectedMap?.map_name }}</template>
      <div class="modal-editor-body map-binding-editor">
        <div class="map-binding-toolbar">
          <strong>配置项</strong>
          <a-button size="mini" type="text" :disabled="!scaleSets.length" @click="addMapBinding">
            添加配置项
          </a-button>
        </div>
        <div v-if="mapForm.bindings.length" class="map-binding-head">
          <span>平台</span><span>画质</span><span>指标标尺集</span><span></span>
        </div>
        <div class="map-binding-list">
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
        <div v-if="!mapForm.bindings.length" class="map-binding-empty">
          暂无配置，热力图将使用动态线性着色
        </div>
      </div>
      <footer class="modal-editor-footer">
        <a-button size="small" :disabled="store.saving" @click="closeMapEditor">取消</a-button>
        <a-button size="small" type="primary" :loading="store.saving" @click="saveMapBindings">保存配置</a-button>
      </footer>
    </a-modal>
  </main>
</template>

<style scoped>
.scale-settings-page { min-width: 1240px; flex-direction: column; }
.scale-workspace { flex: 1; min-height: 0; padding: 0; overflow: hidden; }
.section-toolbar {
  min-height: 48px; padding: 6px 12px; display: flex; align-items: center;
  justify-content: space-between; gap: 10px;
}
.section-toolbar > div { min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.section-toolbar h3 { margin: 0; color: var(--color-text-1); font-size: 14px; }
.section-toolbar span { color: var(--color-text-4); font-size: 11px; }
.load-error { min-height: 180px; display: flex; align-items: center; justify-content: center; gap: 12px; color: rgb(var(--red-6)); }
.library-layout {
  height: 100%; min-height: 0; display: grid;
  grid-template-columns: minmax(440px, 1.04fr) minmax(360px, 0.84fr) minmax(410px, 0.98fr);
}
.library-pane { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.library-pane + .library-pane { border-left: 1px solid var(--color-border-1); }
.library-pane .section-toolbar { border-bottom: 1px solid var(--color-border-1); }
.library-pane .data-table-shell { margin: 10px; }
.library-table-scroll { flex: 1; min-height: 0; max-height: none; overflow: auto; }
.data-table-shell { margin: 0 16px 16px; overflow: hidden; border: 1px solid var(--color-border-1); border-radius: 4px; }
.library-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.library-table th,
.library-table td { height: 42px; padding: 0 8px; border-bottom: 1px solid var(--color-border-1); text-align: left; }
.library-table th { background: var(--color-fill-2); color: var(--color-text-2); font-size: 11px; font-weight: 600; }
.library-table td { color: var(--color-text-2); font-size: 12px; }
.library-table tbody tr:last-child td { border-bottom: 0; }
.library-table tbody tr:hover td { background: color-mix(in srgb, var(--color-fill-2) 45%, transparent); }
.library-table strong { color: var(--color-text-1); font-weight: 500; }
.library-table td:nth-child(2) strong {
  display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.scale-library-table th:nth-child(1), .scale-library-table td:nth-child(1) { width: 38px; }
.scale-library-table th:nth-child(2), .scale-library-table td:nth-child(2) { width: 190px; }
.scale-library-table th:last-child, .scale-library-table td:last-child { width: 142px; }
.set-library-table th:nth-child(1), .set-library-table td:nth-child(1) { width: 38px; }
.set-library-table th:nth-child(2), .set-library-table td:nth-child(2) { width: 112px; }
.set-library-table th:nth-child(3), .set-library-table td:nth-child(3) { width: 54px; }
.set-library-table th:last-child, .set-library-table td:last-child { width: 142px; }
.numeric-cell { color: var(--color-text-3); font-variant-numeric: tabular-nums; }
.action-cell { white-space: nowrap; }
.action-cell :deep(.arco-btn) { padding: 0 4px; }
.compact-actions :deep(.arco-btn) { padding: 0 4px; }
.compact-actions :deep(.arco-btn + .arco-btn) { margin-left: 4px; }
.scale-preview { max-width: 300px; }
.empty-cell { height: 160px !important; color: var(--color-text-4) !important; text-align: center !important; }
.map-list-toolbar > div { flex: 0 0 auto; }
.map-search { width: 132px; }
.map-library-table th:nth-child(1), .map-library-table td:nth-child(1) { width: auto; }
.map-library-table th:nth-child(2), .map-library-table td:nth-child(2) { width: 104px; }
.map-library-table th:last-child, .map-library-table td:last-child { width: 82px; }
.map-library-table td:first-child strong {
  display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.config-status { color: var(--color-text-4); font-size: 11px; white-space: nowrap; }
.config-status.configured { color: rgb(var(--arcoblue-6)); }

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
.set-item-row { min-height: 42px; padding: 5px 7px; border: 1px solid var(--color-border-1); border-radius: 4px; background: var(--color-fill-1); }
.set-scale-preview { width: 112px; }
.preview-placeholder { color: var(--color-text-4); text-align: center; }
.map-binding-toolbar {
  margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;
}
.map-binding-toolbar strong { color: var(--color-text-2); font-size: 12px; }
.map-binding-head,
.map-binding-row {
  display: grid; grid-template-columns: 150px 118px minmax(250px, 1fr) 48px;
  align-items: center; gap: 8px;
}
.map-binding-head { padding: 0 8px 5px; color: var(--color-text-4); font-size: 10px; }
.map-binding-list { display: grid; gap: 6px; }
.map-binding-row {
  min-height: 44px; padding: 6px 7px; border: 1px solid var(--color-border-1);
  border-radius: 4px; background: var(--color-fill-1);
}
.map-binding-empty {
  min-height: 104px; display: flex; align-items: center; justify-content: center;
  border: 1px dashed var(--color-border-2); border-radius: 4px;
  color: var(--color-text-4); font-size: 12px;
}
</style>
