<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'

import { api } from '../api'
import GpmSettingsNav from '../components/GpmSettingsNav.vue'
import { projectedPointStyle } from '../gpmHeatmap/projectConfig'
import { useGpmProjectConfigStore } from '../stores/gpmProjectConfigStore'

const store = useGpmProjectConfigStore()
const configInput = ref(null)
const imageInput = ref(null)
const search = ref('')
const statusFilter = ref('all')
const selectedMapName = ref('')
const pendingImage = ref(null)
const preview = ref({ source: null, points: [], point_count: 0, in_bounds_count: 0 })
const previewLoading = ref(false)
let previewSequence = 0
let imageInspectionSequence = 0

const maps = computed(() => store.catalog.maps || [])
const selectedMap = computed(() => maps.value.find(
  (item) => item.map_name === selectedMapName.value,
) || null)
const filteredMaps = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return maps.value.filter((item) => {
    const searchable = `${item.map_name} ${item.description} ${item.map_id}`.toLocaleLowerCase()
    const statusMatches = statusFilter.value === 'all'
      || (statusFilter.value === 'missing' && !item.image)
      || (statusFilter.value === 'uploaded' && item.image)
    return statusMatches && (!query || searchable.includes(query))
  })
})
const displayedImage = computed(() => pendingImage.value || (selectedMap.value?.image ? {
  url: selectedMap.value.image.image_url,
  width: selectedMap.value.image.width,
  height: selectedMap.value.image.height,
  pending: false,
} : null))
const coordinateFrameStyle = computed(() => {
  const range = selectedMap.value?.range
  return range ? { aspectRatio: `${range[0]} / ${range[1]}` } : {}
})
const nativeOutlineStyle = computed(() => {
  const map = selectedMap.value
  const image = displayedImage.value
  if (!map || !image) return {}
  const coordinateRatio = Number(map.range[0]) / Number(map.range[1])
  const imageRatio = Number(image.width) / Number(image.height)
  if (imageRatio >= coordinateRatio) {
    return { width: '100%', height: `${coordinateRatio / imageRatio * 100}%` }
  }
  return { width: `${imageRatio / coordinateRatio * 100}%`, height: '100%' }
})
const projectedPoints = computed(() => (preview.value.points || []).map((point) => ({
  ...point,
  style: projectedPointStyle(selectedMap.value, point.position),
})).filter((point) => point.style?.inBounds))

function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number)
    : '—'
}

function statusInfo(item) {
  return item?.image
    ? { label: '已上传', tone: 'success' }
    : { label: '未上传', tone: 'muted' }
}

function selectMap(mapName) {
  selectedMapName.value = mapName
}

function clearPendingImage() {
  imageInspectionSequence += 1
  if (pendingImage.value?.url) URL.revokeObjectURL(pendingImage.value.url)
  pendingImage.value = null
  if (imageInput.value) imageInput.value.value = ''
}

function ensureSelection(preferred = selectedMapName.value) {
  const available = maps.value.some((item) => item.map_name === preferred)
  selectedMapName.value = available ? preferred : maps.value[0]?.map_name || ''
}

async function loadPreview() {
  const mapName = selectedMapName.value
  const sequence = ++previewSequence
  preview.value = { source: null, points: [], point_count: 0, in_bounds_count: 0 }
  if (!mapName) return
  previewLoading.value = true
  try {
    const result = await api.gpmProjectMapPreview(mapName)
    if (sequence === previewSequence) preview.value = result
  } catch (error) {
    if (sequence === previewSequence) Message.error(error?.message || '点位预览加载失败')
  } finally {
    if (sequence === previewSequence) previewLoading.value = false
  }
}

async function chooseConfig(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    await store.importConfig(file)
    clearPendingImage()
    ensureSelection()
    Message.success(`已导入 ${store.catalog.summary.total} 张地图`)
  } catch (error) {
    Message.error(error?.message || '配置导入失败')
  }
}

function inspectImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const image = new Image()
    image.onload = () => resolve({ url, width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('图片无法预览'))
    }
    image.src = url
  })
}

async function chooseImage(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !selectedMap.value) return
  clearPendingImage()
  const mapName = selectedMap.value.map_name
  const sequence = ++imageInspectionSequence
  try {
    const inspected = await inspectImage(file)
    if (sequence !== imageInspectionSequence || selectedMap.value?.map_name !== mapName) {
      URL.revokeObjectURL(inspected.url)
      return
    }
    pendingImage.value = {
      ...inspected, file, pending: true,
    }
  } catch (error) {
    Message.error(error?.message || '图片无法预览')
  }
}

async function confirmImage() {
  if (!pendingImage.value?.file || !selectedMap.value) return
  const mapName = selectedMap.value.map_name
  try {
    await store.uploadImage(mapName, pendingImage.value.file)
    clearPendingImage()
    ensureSelection(mapName)
    Message.success('地图图片已更新')
  } catch (error) {
    Message.error(error?.message || '地图图片上传失败')
  }
}

watch(selectedMapName, () => {
  clearPendingImage()
  void loadPreview()
})

onMounted(async () => {
  try {
    await store.load()
    ensureSelection()
  } catch {
    // 页面保留原位错误和重试入口。
  }
})
onBeforeUnmount(() => {
  previewSequence += 1
  clearPendingImage()
})
</script>

<template>
  <main class="gpm-config-page app-body">
    <GpmSettingsNav>
      <input ref="configInput" type="file" accept=".json,application/json" hidden
        @change="chooseConfig">
      <a-button type="primary" size="small" :loading="store.importing"
        @click="configInput?.click()">
        {{ store.catalog.latest_import ? '重新导入配置' : '导入配置' }}
      </a-button>
    </GpmSettingsNav>

    <section v-if="store.error && !maps.length" class="load-error card">
      <span>{{ store.error }}</span>
      <a-button size="small" type="primary" @click="store.load().then(ensureSelection).catch(() => {})">
        重新加载
      </a-button>
    </section>

    <section v-else class="config-workspace card">
      <aside class="map-directory">
        <div class="directory-tools">
          <a-input v-model="search" size="small" allow-clear placeholder="搜索地图名称或 ID" />
          <div class="status-tabs" role="tablist" aria-label="地图配置状态">
            <button v-for="item in [
              ['all', '全部'], ['missing', '未上传'], ['uploaded', '已上传'],
            ]" :key="item[0]" type="button" :class="{ active: statusFilter === item[0] }"
              @click="statusFilter = item[0]">
              {{ item[1] }}
            </button>
          </div>
        </div>
        <div class="map-list" role="listbox" aria-label="项目地图清单">
          <button v-for="item in filteredMaps" :key="item.map_name" type="button"
            class="map-row" :class="{ selected: item.map_name === selectedMapName }"
            :aria-selected="item.map_name === selectedMapName" @click="selectMap(item.map_name)">
            <span class="status-dot" :class="statusInfo(item).tone"></span>
            <span class="map-copy">
              <strong :title="item.map_name">{{ item.map_name }}</strong>
              <small>ID {{ item.map_id }} · {{ formatNumber(item.range[0]) }} × {{ formatNumber(item.range[1]) }}</small>
            </span>
            <span class="row-status" :class="statusInfo(item).tone">{{ statusInfo(item).label }}</span>
          </button>
          <div v-if="!filteredMaps.length" class="directory-empty">
            {{ maps.length ? '没有符合当前筛选的地图' : '导入配置后在这里维护地图图片' }}
          </div>
        </div>
      </aside>

      <section class="map-inspector">
        <template v-if="selectedMap">
          <header class="inspector-heading">
            <h3>{{ selectedMap.map_name }}</h3>
            <div class="image-actions">
              <input ref="imageInput" type="file" accept="image/png,image/jpeg,image/webp" hidden
                @change="chooseImage">
              <template v-if="pendingImage">
                <a-button size="small" @click="clearPendingImage">取消</a-button>
                <a-button type="primary" size="small"
                  :loading="store.uploadingMap === selectedMap.map_name" @click="confirmImage">
                  确认上传
                </a-button>
              </template>
              <a-button v-else size="small" type="primary" @click="imageInput?.click()">
                {{ selectedMap.image ? '替换图片' : '上传图片' }}
              </a-button>
            </div>
          </header>

          <div class="calibration-area">
            <div v-if="displayedImage" class="coordinate-frame" :style="coordinateFrameStyle">
              <img :src="displayedImage.url" alt="地图坐标匹配预览">
              <div class="native-outline" :style="nativeOutlineStyle"></div>
              <span v-for="point in projectedPoints" :key="point.id" class="preview-point"
                :style="point.style" :title="`点位 ${point.index}`"></span>
              <span class="axis-label axis-x-start">{{ formatNumber(selectedMap.origin[0]) }}</span>
              <span class="axis-label axis-x-end">
                {{ formatNumber(selectedMap.origin[0] + selectedMap.range[0]) }}
              </span>
              <span class="axis-label axis-y-start">{{ formatNumber(selectedMap.origin[1]) }}</span>
              <span class="axis-label axis-y-end">
                {{ formatNumber(selectedMap.origin[1] + selectedMap.range[1]) }}
              </span>
              <span v-if="pendingImage" class="pending-badge">待上传预览</span>
            </div>
            <button v-else class="image-drop-empty" type="button" @click="imageInput?.click()">
              <span class="empty-grid"></span>
              <strong>上传地图图片以检查坐标匹配</strong>
              <small>支持 PNG、JPEG、WebP，最大 32 MiB</small>
            </button>
          </div>

          <div class="calibration-facts">
            <div>
              <span>坐标起点</span>
              <strong>X {{ formatNumber(selectedMap.origin[0]) }} · Y {{ formatNumber(selectedMap.origin[1]) }}</strong>
            </div>
            <div>
              <span>坐标范围</span>
              <strong>{{ formatNumber(selectedMap.range[0]) }} × {{ formatNumber(selectedMap.range[1]) }}</strong>
            </div>
            <div>
              <span>图片尺寸</span>
              <strong v-if="displayedImage">{{ displayedImage.width }} × {{ displayedImage.height }} px</strong>
              <strong v-else>未上传</strong>
            </div>
            <div>
              <span>最近点位</span>
              <strong v-if="preview.source">
                {{ preview.in_bounds_count }} / {{ preview.point_count }} 在范围内
              </strong>
              <strong v-else>{{ previewLoading ? '读取中…' : '暂无上报数据' }}</strong>
            </div>
          </div>
        </template>
        <div v-else class="inspector-empty">
          <strong>先导入项目地图配置</strong>
          <span>地图清单、坐标范围和图片状态会集中显示在这里</span>
        </div>
      </section>
    </section>
  </main>
</template>

<style scoped>
.gpm-config-page {
  min-width: 1240px; min-height: 0; flex-direction: column;
}
.success { color: rgb(var(--green-6)) !important; }
.muted { color: var(--color-text-4) !important; }
.load-error, .inspector-empty {
  flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; gap: 12px;
  color: var(--color-text-3);
}
.config-workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(330px, 390px) minmax(0, 1fr); overflow: hidden; }
.map-directory { min-width: 0; min-height: 0; display: flex; flex-direction: column; border-right: 1px solid var(--color-border-1); }
.directory-tools { flex: 0 0 auto; padding: 12px; border-bottom: 1px solid var(--color-border-1); }
.status-tabs { margin-top: 9px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }
.status-tabs button {
  height: 26px; border: 1px solid transparent; border-radius: 4px; background: transparent;
  color: var(--color-text-3); cursor: pointer; font: inherit; font-size: 11px;
}
.status-tabs button:hover { color: var(--color-text-1); background: var(--color-fill-2); }
.status-tabs button.active {
  border-color: rgba(var(--arcoblue-5), .42); color: rgb(var(--arcoblue-6));
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 12%, var(--color-fill-2));
}
.map-list { flex: 1; min-height: 0; overflow-y: auto; padding: 6px; }
.map-row {
  width: 100%; min-height: 54px; padding: 8px 9px; border: 1px solid transparent; border-radius: 5px;
  display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 9px;
  background: transparent; color: inherit; cursor: pointer; text-align: left;
}
.map-row + .map-row { margin-top: 2px; }
.map-row:hover { background: var(--color-fill-2); }
.map-row.selected {
  border-color: rgba(var(--arcoblue-5), .45);
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 10%, var(--color-fill-2));
}
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.map-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.map-copy strong { overflow: hidden; color: var(--color-text-1); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.map-copy small { color: var(--color-text-4); font-size: 10px; font-variant-numeric: tabular-nums; }
.row-status { font-size: 10px; white-space: nowrap; }
.directory-empty { padding: 40px 16px; color: var(--color-text-4); font-size: 12px; text-align: center; }
.map-inspector { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.inspector-heading {
  flex: 0 0 auto; min-height: 52px; padding: 9px 16px; display: flex; align-items: center;
  justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--color-border-1);
}
.inspector-heading h3 {
  min-width: 0; margin: 0; overflow: hidden; color: var(--color-text-1); font-size: 14px;
  text-overflow: ellipsis; white-space: nowrap;
}
.image-actions { display: flex; align-items: center; gap: 8px; }
.calibration-area {
  flex: 1; min-height: 250px; padding: 28px 46px 38px; display: grid; place-items: center;
  overflow: hidden; background: color-mix(in srgb, var(--color-bg-3) 88%, #0d1824);
}
.coordinate-frame {
  position: relative; max-width: 100%; max-height: 100%; width: auto; height: 100%;
  border: 1px solid rgba(var(--arcoblue-5), .75); background: var(--color-bg-2);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, .3), 0 16px 40px rgba(0, 0, 0, .2);
}
.coordinate-frame img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; }
.native-outline {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  border: 1px dashed rgba(var(--orange-5), .9); pointer-events: none;
}
.preview-point {
  position: absolute; width: 7px; height: 7px; transform: translate(-50%, -50%);
  border-radius: 1px; background: rgb(var(--arcoblue-5)); box-shadow: 0 0 0 1px rgba(0,0,0,.8);
}
.axis-label {
  position: absolute; z-index: 2; color: var(--color-text-4); font-family: Consolas, monospace;
  font-size: 9px; pointer-events: none; white-space: nowrap;
}
.axis-x-start { left: 0; bottom: -20px; }
.axis-x-end { right: 0; bottom: -20px; }
.axis-y-start { right: calc(100% + 8px); top: -5px; }
.axis-y-end { right: calc(100% + 8px); bottom: -5px; }
.pending-badge {
  position: absolute; right: 8px; top: 8px; padding: 3px 7px; border-radius: 4px;
  color: rgb(var(--orange-5)); background: rgba(10, 13, 18, .72); font-size: 10px;
}
.image-drop-empty {
  position: relative; width: min(620px, 80%); aspect-ratio: 16 / 9; border: 1px dashed var(--color-border-3);
  border-radius: 6px; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; overflow: hidden; background: var(--color-bg-2); color: var(--color-text-3); cursor: pointer;
}
.image-drop-empty:hover { border-color: rgb(var(--arcoblue-5)); color: var(--color-text-1); }
.image-drop-empty strong { position: relative; font-size: 13px; }
.image-drop-empty small { position: relative; color: var(--color-text-4); font-size: 10px; }
.empty-grid {
  position: absolute; inset: 0; opacity: .25;
  background-image: linear-gradient(var(--color-border-2) 1px, transparent 1px), linear-gradient(90deg, var(--color-border-2) 1px, transparent 1px);
  background-size: 28px 28px;
}
.calibration-facts {
  flex: 0 0 auto; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid var(--color-border-1);
}
.calibration-facts > div { min-width: 0; padding: 9px 13px; border-right: 1px solid var(--color-border-1); }
.calibration-facts > div:nth-child(4n) { border-right: none; }
.calibration-facts span { display: block; margin-bottom: 3px; color: var(--color-text-4); font-size: 9px; }
.calibration-facts strong {
  display: block; overflow: hidden; color: var(--color-text-2); font-size: 11px;
  font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap;
}
.inspector-empty { flex-direction: column; }
.inspector-empty strong { color: var(--color-text-2); }
.inspector-empty span { font-size: 11px; }
@media (max-width: 900px) {
  .config-workspace { grid-template-columns: 1fr; overflow-y: auto; }
  .map-directory { min-height: 280px; border-right: none; border-bottom: 1px solid var(--color-border-1); }
  .map-inspector { min-height: 540px; }
}
</style>
