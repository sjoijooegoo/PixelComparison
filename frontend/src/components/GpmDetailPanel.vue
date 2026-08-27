<script setup>
import { reactive, ref, watch } from 'vue'

import GpmDetailNode from './GpmDetailNode.vue'

const props = defineProps({
  point: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const openRootIndex = ref(null)
const expansionState = reactive({})
// 每次详情重新获取（即使仍是同一 point id）都视为一次新会话；手动刷新应清空
// 本页临时展开状态，用户折叠再展开同一份数据则仍保留子节点路径。
watch(() => props.point, () => {
  openRootIndex.value = null
  Object.keys(expansionState).forEach((key) => delete expansionState[key])
})

function toggleRoot(index) {
  openRootIndex.value = openRootIndex.value === index ? null : index
}
</script>

<template>
  <section class="detail-card card">
    <header>
      <strong>详细数据</strong>
    </header>
    <div v-if="loading && !point" class="panel-state"><a-spin /> 正在加载点位详情</div>
    <div v-else-if="error && !point" class="panel-state error">{{ error }}</div>
    <div v-else-if="point" class="detail-list">
      <GpmDetailNode v-for="(node, index) in point.detail_data || []"
        :key="`${point.id}-${node.name}-${index}`" :node="node"
        :expanded="openRootIndex === index" :expansion-state="expansionState"
        :node-path="String(index)" @toggle="toggleRoot(index)" />
    </div>
    <div v-else class="panel-state">选择地图点位或下方截图查看详细数据</div>
  </section>
</template>

<style scoped>
.detail-card { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
header {
  height: 43px; flex: 0 0 43px; display: flex; align-items: center; gap: 10px;
  padding: 0 14px; border-bottom: 1px solid var(--color-border-1);
}
header strong { font-size: 14px; }
.detail-list { flex: 1; min-height: 0; overflow: auto; padding: 6px 8px 10px; }
.panel-state { flex: 1; display: flex; gap: 8px; align-items: center; justify-content: center; color: var(--color-text-3); }
.panel-state.error { color: rgb(var(--red-6)); }
</style>
