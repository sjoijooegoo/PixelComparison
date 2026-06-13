<script setup>
import { useStore, PAGE_SIZE } from '../store'

const store = useStore()

// 差异率按数值分级着色(不再依赖通过/警告/失败状态)
function diffClass(s) {
  if (s.diff_pct === null) return 'diff-dim'
  if (s.diff_pct >= 2) return 'diff-fail'
  if (s.diff_pct >= 0.3) return 'diff-warn'
  if (s.diff_pct < 0.005) return 'diff-dim'
  return ''
}

let searchTimer
function onSearch(val) {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    store.sceneSearch = val
    store.page = 1
    store.loadScenes()
  }, 300)
}
</script>

<template>
  <section class="scene-panel card">
    <div class="head">
      <div class="head-top">
        <b style="color: rgb(var(--arcoblue-6))">对比结果</b>
        <span class="text-secondary" style="font-size:12px">{{ store.sceneTotal }} 个场景</span>
        <a-button size="mini" class="sort-btn" :type="store.sceneSort === 'diff' ? 'primary' : 'secondary'"
          @click="store.toggleSceneSort()">
          <template #icon>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor"
              stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 2v8M3 10 1.5 8.3M3 10l1.5-1.7M7 3h4M7 6h3M7 9h2" />
            </svg>
          </template>
          {{ store.sceneSort === 'diff' ? '按差异率' : '按名称' }}
        </a-button>
      </div>
      <a-input size="small" placeholder="搜索场景名称" allow-clear
        :model-value="store.sceneSearch" @input="onSearch" @clear="onSearch('')" />
    </div>

    <div class="cols text-secondary"><span style="flex:1">场景名称</span><span style="width:56px; text-align:right">差异率</span></div>

    <a-spin :loading="store.loading" class="list-wrap">
      <div class="list">
        <div v-for="s in store.scenes" :key="s.id" class="item"
          :class="{ selected: s.id === store.detail?.id }"
          @click="store.selectScene(s.id)">
          <img :src="s.thumb_url" loading="lazy" alt="">
          <span class="name" :title="s.name">{{ s.name }}</span>
          <span class="diff mono" :class="diffClass(s)">
            {{ s.diff_pct !== null ? s.diff_pct.toFixed(2) + '%' : '—' }}
          </span>
        </div>
        <a-empty v-if="!store.scenes.length && !store.loading" />
      </div>
    </a-spin>

    <div class="foot">
      <a-pagination size="mini" simple
        :total="store.sceneTotal" :page-size="PAGE_SIZE"
        :current="store.page"
        @change="(p) => { store.page = p; store.loadScenes() }" />
    </div>
  </section>
</template>

<style scoped>
.scene-panel { width: 300px; flex: 0 0 300px; display: flex; flex-direction: column; min-height: 0; }
.head { padding: 10px 12px 6px; display: flex; flex-direction: column; gap: 8px; }
.head-top { display: flex; align-items: center; gap: 8px; }
.sort-btn { margin-left: auto; }
.cols { display: flex; padding: 4px 12px; font-size: 12px; border-bottom: 1px solid var(--color-border-2); }
.list-wrap { flex: 1; min-height: 0; }
.list { height: 100%; overflow-y: auto; }
.item {
  display: flex; align-items: center; gap: 8px; padding: 7px 12px; cursor: pointer;
  border-bottom: 1px solid var(--color-border-1);
}
.item:hover { background: var(--color-fill-1); }
.item.selected { background: var(--color-fill-2); box-shadow: inset 2px 0 0 rgb(var(--arcoblue-6)); }
.item img {
  width: 56px; height: 32px; object-fit: cover; border-radius: 4px;
  background: #222; flex: 0 0 56px; border: 1px solid var(--color-border-2);
}
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.diff { width: 52px; text-align: right; font-size: 12px; }
.foot { padding: 8px 12px; border-top: 1px solid var(--color-border-2); display: flex; justify-content: center; }
</style>
