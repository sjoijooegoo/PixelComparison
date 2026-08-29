<script setup>
defineProps({ items: { type: Array, default: () => [] }, canCreate: Boolean })
const emit = defineEmits(['create', 'copy', 'edit', 'delete'])
</script>

<template>
  <section class="library-pane">
    <header><div><h3>指标标尺集</h3><span>{{ items.length }} 个</span></div><a-button type="primary" size="small" :disabled="!canCreate" @click="emit('create')">新建标尺集</a-button></header>
    <div class="table-shell"><table><thead><tr><th>ID</th><th>名称</th><th>操作</th></tr></thead><tbody>
      <tr v-for="item in items" :key="item.id"><td class="numeric">{{ item.id }}</td><td><strong :title="item.name">{{ item.name }}</strong></td><td class="actions"><a-button size="mini" type="text" @click="emit('copy', item)">复制</a-button><a-button size="mini" type="text" @click="emit('edit', item)">编辑</a-button><a-button size="mini" type="text" status="danger" @click="emit('delete', item)">删除</a-button></td></tr>
      <tr v-if="!items.length"><td colspan="3" class="empty">暂无指标标尺集</td></tr>
    </tbody></table></div>
  </section>
</template>

<style scoped>
.library-pane { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
header { min-height: 48px; padding: 6px 12px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--color-border-1); }
header > div { display: flex; align-items: baseline; gap: 10px; } h3 { margin: 0; color: var(--color-text-1); font-size: 14px; } header span { color: var(--color-text-4); font-size: 11px; }
.table-shell { flex: 1; min-height: 0; margin: 10px; overflow: auto; border: 1px solid var(--color-border-1); border-radius: 4px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; } th, td { height: 42px; padding: 0 8px; border-bottom: 1px solid var(--color-border-1); text-align: left; } th { background: var(--color-fill-2); color: var(--color-text-2); font-size: 11px; } td { color: var(--color-text-2); font-size: 12px; } tbody tr:last-child td { border-bottom: 0; } tbody tr:hover td { background: color-mix(in srgb, var(--color-fill-2) 45%, transparent); }
th:first-child, td:first-child { width: 38px; } th:last-child, td:last-child { width: 120px; } strong { display: block; overflow: hidden; color: var(--color-text-1); font-weight: 500; text-overflow: ellipsis; white-space: nowrap; } .numeric { color: var(--color-text-3); font-variant-numeric: tabular-nums; } .actions { white-space: nowrap; } .actions :deep(.arco-btn) { padding: 0 4px; } .actions :deep(.arco-btn + .arco-btn) { margin-left: 4px; } .empty { height: 160px !important; color: var(--color-text-4) !important; text-align: center !important; }
</style>
