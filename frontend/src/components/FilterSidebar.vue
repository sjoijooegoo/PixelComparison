<script setup>
import { Message } from '@arco-design/web-vue'
import { useStore } from '../store'

const store = useStore()

async function apply() {
  await store.loadBatches()
  Message.success('筛选已应用')
}

async function reset() {
  store.filters = { project: '', platform: '', branch: '', baseline: '', status: '' }
  await apply()
}
</script>

<template>
  <aside class="sidebar card">
    <div class="scroll">
      <div class="head">
        <b>筛选条件</b>
        <a-link @click="reset">清空</a-link>
      </div>

      <div class="group">
        <div class="label">项目</div>
        <a-select v-model="store.filters.project" placeholder="全部项目" allow-clear size="small">
          <a-option v-for="p in store.meta.projects" :key="p" :value="p">{{ p }}</a-option>
        </a-select>
      </div>
      <div class="group">
        <div class="label">平台</div>
        <a-select v-model="store.filters.platform" placeholder="全部平台" allow-clear size="small">
          <a-option v-for="p in store.meta.platforms" :key="p" :value="p">{{ p }}</a-option>
        </a-select>
      </div>
      <div class="group">
        <div class="label">分支 / 版本</div>
        <a-select v-model="store.filters.branch" placeholder="全部版本" allow-clear size="small">
          <a-option v-for="b in store.meta.branches" :key="b" :value="b">{{ b }}</a-option>
        </a-select>
      </div>
      <div class="group">
        <div class="label">基线版本</div>
        <a-select v-model="store.filters.baseline" placeholder="全部基线" allow-clear size="small">
          <a-option v-for="b in store.meta.baselines" :key="b" :value="b">{{ b }}</a-option>
        </a-select>
      </div>
      <div class="group">
        <div class="label">创建时间</div>
        <a-range-picker size="small" style="width: 100%" />
      </div>

      <a-button type="primary" long @click="apply">应用筛选</a-button>
    </div>
    <div class="foot">
      <a-button long @click="Message.info('当前筛选已保存为视图(示例)')">保存为视图</a-button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar { width: 220px; flex: 0 0 220px; display: flex; flex-direction: column; min-height: 0; }
.scroll { flex: 1; overflow-y: auto; padding: 14px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.group { margin-bottom: 14px; }
.label { color: var(--color-text-3); font-size: 12px; margin-bottom: 5px; }
.foot { padding: 12px 14px; border-top: 1px solid var(--color-border-2); }
</style>
