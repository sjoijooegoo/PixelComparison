<script setup>
import { Message } from '@arco-design/web-vue'
import { theme, toggleTheme } from '../theme'
import { useStore } from '../store'

defineProps({ active: String })
defineEmits(['update:active'])

const store = useStore()

const tabs = [
  { key: 'batch', label: '批次管理' },
  { key: '对比结果', label: '对比结果' },
  { key: '项目设置', label: '项目设置' },
]

async function refresh() {
  if (store.activeTab === '对比结果') {
    await store.loadComparisons()
  } else {
    await store.refreshBatches()
  }
  Message.success('已刷新')
}
</script>

<template>
  <header class="topbar">
    <div class="logo">
      <!-- 两帧叠加 + 差异点:像素对比的意象 -->
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="2.5" y="2.5" width="13" height="13" rx="3.5" fill="rgb(var(--arcoblue-6))" />
        <rect x="8.5" y="8.5" width="13" height="13" rx="3.5" fill="none"
          stroke="rgb(var(--arcoblue-5))" stroke-width="2" />
        <circle cx="18.5" cy="5.5" r="3" fill="rgb(var(--red-5))" />
      </svg>
      PixelComparison
    </div>
    <nav class="tabs">
      <button v-for="t in tabs" :key="t.key" class="tab"
        :class="{ active: active === t.key }"
        @click="$emit('update:active', t.key)">{{ t.label }}</button>
    </nav>
    <div class="actions">
      <template v-if="active === 'batch' || active === '对比结果'">
        <a-tooltip content="刷新">
          <button class="icon-btn" @click="refresh">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
            </svg>
          </button>
        </a-tooltip>
        <a-tooltip content="手动上报">
          <button class="icon-btn" @click="store.uploadVisible = true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M5 20h14" />
            </svg>
          </button>
        </a-tooltip>
      </template>
      <a-tooltip :content="theme === 'dark' ? '切换亮色' : '切换暗色'">
        <button class="icon-btn" @click="toggleTheme">
          <svg v-if="theme === 'dark'" width="15" height="15" viewBox="0 0 16 16" fill="none"
            stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <circle cx="8" cy="8" r="3.2" />
            <path d="M8 1.2v1.8M8 13v1.8M1.2 8H3M13 8h1.8M3.2 3.2l1.3 1.3M11.5 11.5l1.3 1.3M12.8 3.2l-1.3 1.3M4.5 11.5l-1.3 1.3" />
          </svg>
          <svg v-else width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
            <path d="M13.8 9.7A6 6 0 0 1 6.3 2.2a6 6 0 1 0 7.5 7.5z" />
          </svg>
        </button>
      </a-tooltip>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: 52px; flex: 0 0 52px; display: flex; align-items: center; gap: 24px;
  padding: 0 20px; background: var(--color-bg-2);
  border-bottom: 1px solid var(--color-border-1);
}
.logo { font-size: 16px; font-weight: 700; display: flex; align-items: center; gap: 9px; letter-spacing: .2px; }
.tabs { display: flex; gap: 8px; height: 100%; }
.tab {
  border: none; background: none; padding: 0 16px; font-size: 14px; cursor: pointer;
  color: var(--color-text-2); position: relative; font-family: inherit;
}
.tab:hover { color: var(--color-text-1); }
.tab.active { color: rgb(var(--arcoblue-6)); font-weight: 600; }
.tab.active::after {
  content: ""; position: absolute; left: 12px; right: 12px; bottom: 0;
  height: 2px; background: rgb(var(--arcoblue-6)); border-radius: 2px;
}
.actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.icon-btn {
  width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--color-border-2); background: transparent;
  color: var(--color-text-2); display: flex; align-items: center; justify-content: center;
}
.icon-btn:hover { background: var(--color-fill-2); color: var(--color-text-1); }
</style>
