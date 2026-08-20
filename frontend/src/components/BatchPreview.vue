<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { api, isRequestCancelled } from '../api'
import { p4Label } from '../store'
import { batchPreviewImage } from './batchPreviewImages'
import { completeQualityRuns, preferredPreviewQuality, qualityLabel } from '../qualityRuns'

const props = defineProps({
  visible: { type: Boolean, default: false },
  batch: { type: Object, default: null },
})
const emit = defineEmits(['update:visible'])

const loading = ref(false)
const shots = ref([])
const selectedQuality = ref(null)
const previewVisible = ref(false)
const previewCurrent = ref(0)
const thumbnailRetryNonce = ref({})
const thumbnailFailed = ref(new Set())
const thumbnailAttempts = new Map()
const thumbnailTimers = new Set()
let shotsRequestId = 0
let shotsController = null
const previewShots = computed(() => shots.value.map((shot) => ({
  ...shot,
  ...batchPreviewImage(shot.url),
})))
const originalUrls = computed(() => previewShots.value.map((shot) => shot.originalUrl))
const qualityRuns = computed(() => completeQualityRuns(props.batch))

function clearThumbnailTimers() {
  for (const timer of thumbnailTimers) clearTimeout(timer)
  thumbnailTimers.clear()
  thumbnailAttempts.clear()
  thumbnailRetryNonce.value = {}
  thumbnailFailed.value = new Set()
}

// 同时监听批次 ID；关闭、切批次或卸载会 abort，序号再阻止已经到达的旧响应回写。
watch(() => [props.visible, props.batch?.id], ([open]) => {
  if (open) selectedQuality.value = preferredPreviewQuality(props.batch)
  else selectedQuality.value = null
}, { immediate: true })

watch(() => [props.visible, props.batch?.id, selectedQuality.value], async ([open, batchId, quality]) => {
  const requestId = ++shotsRequestId
  shotsController?.abort()
  shotsController = null
  previewVisible.value = false
  clearThumbnailTimers()
  if (!open || !batchId || quality == null) {
    loading.value = false
    shots.value = []
    return
  }

  const controller = new AbortController()
  shotsController = controller
  loading.value = true
  shots.value = []
  try {
    const { items } = await api.qualityRunScreenshots(batchId, quality, {
      signal: controller.signal,
    })
    if (requestId !== shotsRequestId || props.batch?.id !== batchId
      || Number(selectedQuality.value) !== Number(quality) || !props.visible) return
    shots.value = items
  } catch (error) {
    if (!isRequestCancelled(error) && requestId === shotsRequestId) {
      Message.error(error.message || '加载截图失败')
    }
  } finally {
    if (requestId === shotsRequestId) {
      loading.value = false
      if (shotsController === controller) shotsController = null
    }
  }
}, { immediate: true })

onUnmounted(() => {
  ++shotsRequestId
  shotsController?.abort()
  clearThumbnailTimers()
})

function close() {
  previewVisible.value = false
  emit('update:visible', false)
}

function openOriginal(index) {
  previewCurrent.value = index
  previewVisible.value = true
}

function thumbnailSrc(shot) {
  const nonce = thumbnailRetryNonce.value[shot.scene_name]
  return nonce ? `${shot.thumbnailUrl}&retry=${nonce}` : shot.thumbnailUrl
}

// 严格模式未命中时只重试 /thumb；多次失败后给用户显式重试入口，不永久黑屏。
function retryThumbnail(shot) {
  const attempt = (thumbnailAttempts.get(shot.scene_name) || 0) + 1
  thumbnailAttempts.set(shot.scene_name, attempt)
  if (attempt > 15) {
    thumbnailFailed.value = new Set([...thumbnailFailed.value, shot.scene_name])
    return
  }
  const delay = Math.min(250 * attempt, 1200)
  const timer = setTimeout(() => {
    thumbnailTimers.delete(timer)
    if (!props.visible) return
    thumbnailRetryNonce.value = {
      ...thumbnailRetryNonce.value,
      [shot.scene_name]: Date.now(),
    }
  }, delay)
  thumbnailTimers.add(timer)
}

function retryThumbnailNow(shot) {
  thumbnailAttempts.set(shot.scene_name, 0)
  const failed = new Set(thumbnailFailed.value)
  failed.delete(shot.scene_name)
  thumbnailFailed.value = failed
  thumbnailRetryNonce.value = {
    ...thumbnailRetryNonce.value,
    [shot.scene_name]: Date.now(),
  }
}
</script>

<template>
  <a-modal :visible="visible" @update:visible="close" :footer="false" width="82%"
    title-align="start" :body-style="{ maxHeight: '72vh', overflow: 'auto' }">
    <template #title>
      <span v-if="batch" class="title">
        批次 <span class="mono">#{{ batch.id }}</span>
        <span class="dot">·</span>{{ batch.scene_id }}
        <span class="dot">·</span>{{ batch.platform }}
        <span class="dot">·</span>{{ p4Label(batch.p4_version) }}
        <span class="dot">·</span>{{ qualityLabel(selectedQuality) }}
        <span class="dot">·</span>{{ shots.length }} 张
      </span>
    </template>

    <div v-if="qualityRuns.length > 1" class="quality-tabs">
      <span class="quality-tabs-label">画质</span>
      <a-radio-group v-model="selectedQuality" type="button" size="small">
        <a-radio v-for="run in qualityRuns" :key="run.shading_quality"
          :value="run.shading_quality">
          {{ qualityLabel(run.shading_quality) }} · {{ run.ready_screenshot_count }} 张
        </a-radio>
      </a-radio-group>
    </div>

    <a-spin :loading="loading" style="display:block; min-height: 120px">
      <a-image-preview-group v-if="shots.length" infinite
        v-model:visible="previewVisible" v-model:current="previewCurrent"
        :src-list="originalUrls">
        <div class="grid">
          <div v-for="(s, index) in previewShots" :key="s.scene_name" class="cell">
            <img :src="thumbnailSrc(s)" :alt="s.scene_name" loading="lazy" decoding="async"
              @error="retryThumbnail(s)" @click="openOriginal(index)">
            <button v-if="thumbnailFailed.has(s.scene_name)" class="thumb-retry"
              @click.stop="retryThumbnailNow(s)">缩略图生成较慢，重试</button>
            <div class="name" :title="s.scene_name">{{ s.scene_name }}</div>
          </div>
        </div>
      </a-image-preview-group>
      <a-empty v-else-if="!loading" description="该批次暂无截图" style="margin: 30px 0" />
    </a-spin>
  </a-modal>
</template>

<style scoped>
.title { font-size: 14px; }
.title .dot { color: var(--color-text-4); margin: 0 6px; }
.quality-tabs {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
  padding-bottom: 10px; border-bottom: 1px solid var(--color-border-2);
}
.quality-tabs-label { color: var(--color-text-3); font-size: 12px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}
.cell {
  position: relative;
  border: 1px solid var(--color-border-2);
  border-radius: 8px;
  overflow: hidden;
  background: #0d1117;
}
.cell > img {
  display: block; width: 100%; height: 120px; object-fit: cover;
  cursor: zoom-in; background: #0d1117;
}
.thumb-retry {
  position: absolute; left: 50%; top: 60px; transform: translate(-50%, -50%);
  padding: 5px 9px; border: 1px solid var(--color-border-3); border-radius: 6px;
  color: var(--color-text-2); background: rgba(20, 20, 20, .88); cursor: pointer;
  font: inherit; font-size: 11px; white-space: nowrap;
}
.name {
  padding: 5px 8px;
  font-size: 11px;
  color: var(--color-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--color-fill-1);
}
</style>
