<script setup>
defineProps({ active: String })
defineEmits(['update:active'])

const tabs = [
  { key: 'batch', label: '批次管理' },
  { key: '对比结果', label: '对比结果' },
  { key: '基线管理', label: '基线管理' },
  { key: '项目设置', label: '项目设置' },
]
</script>

<template>
  <header class="topbar panel-border-b">
    <div class="logo">📷 PixelComparison</div>
    <nav class="tabs">
      <button v-for="t in tabs" :key="t.key" class="tab"
        :class="{ active: active === t.key }"
        @click="$emit('update:active', t.key)">{{ t.label }}</button>
    </nav>
  </header>
</template>

<style scoped>
.topbar { height: 56px; flex: 0 0 56px; display: flex; align-items: center; gap: 24px; padding: 0 20px; }
.logo { font-size: 18px; font-weight: 700; }
.tabs { display: flex; gap: 8px; height: 100%; }
.tab {
  border: none; background: none; padding: 0 16px; font-size: 14px; cursor: pointer;
  color: var(--color-text-2); position: relative;
}
.tab.active { color: rgb(var(--arcoblue-6)); font-weight: 600; }
.tab.active::after {
  content: ""; position: absolute; left: 12px; right: 12px; bottom: 0;
  height: 2px; background: rgb(var(--arcoblue-6)); border-radius: 2px;
}
</style>
