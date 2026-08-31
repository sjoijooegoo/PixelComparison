<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ maps: { type: Array, default: () => [] } })
const emit = defineEmits(['create', 'edit', 'delete'])
const search = ref('')
const filteredMaps = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return props.maps.filter((map) => !query || (
    map.map_name.toLocaleLowerCase().includes(query) || String(map.id).includes(query)
  ))
})
</script>

<template>
  <section class="library-pane map-pane">
    <header class="section-toolbar">
      <div><h3>地图配置</h3><span>{{ maps.length }} 张地图</span></div>
      <div class="toolbar-actions">
        <a-input v-model="search" class="map-search" size="small" allow-clear placeholder="搜索地图" />
        <a-button type="primary" size="small" @click="emit('create')">新建地图</a-button>
      </div>
    </header>
    <div class="table-shell">
      <table class="library-table map-table">
        <thead><tr><th>ID</th><th>地图名称</th><th>图片</th><th>标尺</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="map in filteredMaps" :key="map.map_name">
            <td class="numeric-cell">{{ map.id }}</td>
            <td><strong :title="map.map_name">{{ map.map_name }}</strong></td>
            <td><span class="status" :class="{ configured: map.image }">{{ map.image ? '已上传' : '未上传' }}</span></td>
            <td><span class="status" :class="{ configured: map.bindings?.length }">{{ map.bindings?.length ? '已配置' : '未配置' }}</span></td>
            <td class="action-cell">
              <a-button size="mini" type="text" @click="emit('edit', map)">配置</a-button>
              <a-button size="mini" type="text" status="danger" @click="emit('delete', map)">删除</a-button>
            </td>
          </tr>
          <tr v-if="!filteredMaps.length"><td colspan="5" class="empty-cell">暂无地图</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.library-pane { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.section-toolbar { min-height: 48px; padding: 6px 12px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--color-border-1); }
.section-toolbar > div { min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.section-toolbar h3 { margin: 0; color: var(--color-text-1); font-size: 14px; }
.section-toolbar span { color: var(--color-text-4); font-size: 11px; }
.toolbar-actions { flex: 0 0 auto; align-items: center !important; gap: 7px !important; }
.map-search { width: 132px; }
.table-shell { flex: 1; min-height: 0; margin: 10px; overflow: auto; border: 1px solid var(--color-border-1); border-radius: 4px; }
.library-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { height: 42px; padding: 0 8px; border-bottom: 1px solid var(--color-border-1); text-align: left; }
th { background: var(--color-fill-2); color: var(--color-text-2); font-size: 11px; font-weight: 600; white-space: nowrap; }
td { color: var(--color-text-2); font-size: 12px; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: color-mix(in srgb, var(--color-fill-2) 45%, transparent); }
strong {
  display: block; overflow: hidden; margin-bottom: -2px; padding-bottom: 2px;
  color: var(--color-text-1); font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-weight: 500; line-height: 18px; text-overflow: ellipsis; white-space: nowrap;
}
.map-table th:nth-child(1), .map-table td:nth-child(1) { width: 38px; }
.map-table th:nth-child(3), .map-table td:nth-child(3), .map-table th:nth-child(4), .map-table td:nth-child(4) { width: 62px; }
.map-table th:last-child, .map-table td:last-child { width: 82px; }
.numeric-cell { color: var(--color-text-3); font-variant-numeric: tabular-nums; }
.action-cell { white-space: nowrap; }
.action-cell :deep(.arco-btn) { padding: 0 4px; }
.action-cell :deep(.arco-btn + .arco-btn) { margin-left: 6px; }
.status { color: var(--color-text-4); font-size: 11px; white-space: nowrap; }
.status.configured { color: rgb(var(--green-6)); }
.empty-cell { height: 160px !important; color: var(--color-text-4) !important; text-align: center !important; }
</style>
