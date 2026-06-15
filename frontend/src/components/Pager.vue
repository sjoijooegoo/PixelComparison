<script setup>
import { computed } from 'vue'

const props = defineProps({
  total: { type: Number, default: 0 },
  pageSize: { type: Number, required: true },
  current: { type: Number, default: 1 },
  unit: { type: String, default: '' },   // 传入则显示「共 N 个{unit}」
})
const emit = defineEmits(['change'])

const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

function go(p) {
  const np = Math.min(pages.value, Math.max(1, p))
  if (np !== props.current) emit('change', np)
}
</script>

<template>
  <div class="pager">
    <span v-if="unit" class="pager-total">共 {{ total }} 个{{ unit }}</span>
    <!-- 连体分段样式,与对比图右下角的场景切换器一致 -->
    <a-button-group size="mini">
      <a-button :disabled="current <= 1" @click="go(current - 1)">‹ 上一页</a-button>
      <a-button disabled>{{ current }}/{{ pages }}</a-button>
      <a-button :disabled="current >= pages" @click="go(current + 1)">下一页 ›</a-button>
    </a-button-group>
  </div>
</template>

<style scoped>
.pager { display: inline-flex; align-items: center; gap: 8px; }
.pager-total { font-size: 12px; color: var(--color-text-3); white-space: nowrap; }
</style>
