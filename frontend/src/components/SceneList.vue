<script setup>
import { computed } from 'vue'
import { useStore, STATUS_META, PAGE_SIZE } from '../store'

const store = useStore()

const chips = computed(() => {
  const base = [
    { key: '', label: '全部', count: store.counts.all },
    { key: 'fail', label: '失败', count: store.counts.fail },
    { key: 'warn', label: '警告', count: store.counts.warn },
    { key: 'pass', label: '通过', count: store.counts.pass },
  ]
  // 新增 / 缺失只有出现时才显示
  for (const key of ['added', 'missing']) {
    if (store.counts[key] > 0) base.push({ key, label: STATUS_META[key].label, count: store.counts[key] })
  }
  return base
})

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
  <section class="scene-panel panel-border-r">
    <div class="head">
      <b style="color: rgb(var(--arcoblue-6))">对比结果</b>
      <div class="chips">
        <a-tag v-for="c in chips" :key="c.key" checkable size="small"
          :checked="store.sceneFilter === c.key"
          :color="c.key ? STATUS_META[c.key].color : 'arcoblue'"
          @check="store.setSceneFilter(c.key)">
          {{ c.label }} {{ c.count }}
        </a-tag>
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
          <span class="diff mono" :class="{ 'diff-fail': s.status === 'fail' }">
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
.chips { display: flex; gap: 4px; flex-wrap: wrap; }
.cols { display: flex; padding: 4px 12px; font-size: 12px; border-bottom: 1px solid var(--color-border-2); }
.list-wrap { flex: 1; min-height: 0; }
.list { height: 100%; overflow-y: auto; }
.item {
  display: flex; align-items: center; gap: 6px; padding: 6px 12px; cursor: pointer;
  border-bottom: 1px solid var(--color-border-1);
}
.item:hover { background: var(--color-fill-1); }
.item.selected { background: rgb(var(--arcoblue-1)); box-shadow: inset 2px 0 0 rgb(var(--arcoblue-6)); }
.item img { width: 40px; height: 24px; object-fit: cover; border-radius: 3px; background: #222; flex: 0 0 40px; }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.diff { width: 52px; text-align: right; font-size: 12px; }
.foot { padding: 8px 12px; border-top: 1px solid var(--color-border-2); display: flex; justify-content: center; }
</style>
