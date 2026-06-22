<script setup>
import { ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { api } from '../api'
import { p4Label } from '../store'

const props = defineProps({
  visible: { type: Boolean, default: false },
  batch: { type: Object, default: null },
})
const emit = defineEmits(['update:visible'])

const loading = ref(false)
const shots = ref([])

// 弹窗打开时按批次拉全部截图
watch(
  () => props.visible,
  async (open) => {
    if (!open || !props.batch) return
    loading.value = true
    shots.value = []
    try {
      const { items } = await api.batchScreenshots(props.batch.id)
      shots.value = items
    } catch (e) {
      Message.error(e.message || '加载截图失败')
    } finally {
      loading.value = false
    }
  },
)

function close() {
  emit('update:visible', false)
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
        <span class="dot">·</span>{{ batch.shading_quality_label }}
        <span class="dot">·</span>{{ shots.length }} 张
      </span>
    </template>

    <a-spin :loading="loading" style="display:block; min-height: 120px">
      <a-image-preview-group v-if="shots.length" infinite>
        <div class="grid">
          <div v-for="s in shots" :key="s.scene_name" class="cell">
            <a-image :src="s.url" :alt="s.scene_name" loading="lazy"
              width="100%" height="100%" fit="cover" show-loader />
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
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}
.cell {
  border: 1px solid var(--color-border-2);
  border-radius: 8px;
  overflow: hidden;
  background: #0d1117;
}
.cell :deep(.arco-image) { display: block; width: 100%; height: 120px; }
.cell :deep(.arco-image-img) { cursor: zoom-in; }
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
