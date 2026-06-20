<script setup>
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore, p4Label } from '../store'

const store = useStore()
const c = computed(() => store.orientedComparison)   // 按当前换向(flip)取向展示
const open = ref(false)

function diffColor(v) {
  v = v ?? 0
  if (v >= store.settings.fail_threshold) return 'rgb(var(--red-6))'
  if (v >= store.settings.warn_threshold) return 'rgb(var(--orange-6))'
  return 'rgb(var(--green-6))'
}

function pick(item) {
  open.value = false
  if (item.id !== c.value?.id) store.openComparison(item)
}

async function rerun() {
  try {
    await store.rerunComparison()
    Message.success('已重新对比')
  } catch (e) {
    Message.error(e.message || '重新对比失败')
  }
}
</script>

<template>
  <div v-if="c" class="summary card">
    <!-- 对比对 = 历史切换器:点击展开过去的对比 -->
    <a-popover v-model:popup-visible="open" trigger="click" position="bl"
      :content-style="{ padding: '6px' }">
      <button class="pair-trigger" :class="{ open }">
        <span class="pair">
          <span class="role role-base">基线</span>
          <span class="mono">#{{ c.ref_batch_id }}</span>
          <span class="text-secondary br">{{ p4Label(c.ref_p4_version) }}</span>
          <span class="vs">VS</span>
          <span class="role role-cur">对比批次</span>
          <span class="mono">#{{ c.batch_id }}</span>
          <span class="text-secondary br">{{ p4Label(c.p4_version) }}</span>
        </span>
        <svg class="caret" width="12" height="12" viewBox="0 0 12 12" fill="none"
          stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 4.5 6 7.5l3-3" />
        </svg>
      </button>

      <template #content>
        <div class="hist-pop">
          <div class="hist-head text-secondary">
            对比历史 <b>{{ store.comparisons.length }}</b> <span class="cap">/ 最多 25</span>
          </div>
          <div class="hist-list">
            <button v-for="h in store.comparisons" :key="h.id" class="hist-item"
              :class="{ active: h.id === c.id }" @click="pick(h)">
              <div class="row1">
                <span class="mono ref">#{{ h.ref_batch_id }}</span>
                <span class="vs">vs</span>
                <span class="mono cur">#{{ h.batch_id }}</span>
                <span class="diff mono" :style="{ color: diffColor(h.diff_avg) }">
                  {{ (h.diff_avg ?? 0).toFixed(2) }}%</span>
              </div>
              <div class="scene">{{ h.scene_id }}</div>
              <div class="meta text-secondary">
                <span>{{ p4Label(h.ref_p4_version) }}</span>
                <span class="arrow">→</span>
                <span>{{ p4Label(h.p4_version) }}</span>
              </div>
              <div class="meta text-secondary">
                <span>{{ h.ref_created_at }}</span>
                <span class="arrow">→</span>
                <span>{{ h.batch_created_at }}</span>
              </div>
            </button>
            <a-empty v-if="!store.comparisons.length" description="暂无对比记录" style="margin:24px 0" />
          </div>
        </div>
      </template>
    </a-popover>

    <a-tooltip content="交换基线 / 对比">
      <button class="swap-btn" :disabled="store.running" @click="store.swapComparison()" aria-label="交换基线/对比">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M7 4 3 8l4 4" /><path d="M3 8h14" />
          <path d="m17 20 4-4-4-4" /><path d="M21 16H7" />
        </svg>
      </button>
    </a-tooltip>

    <div class="spacer"></div>

    <div class="facts">
      <span class="fact"><i class="k">场景ID</i><b>{{ c.scene_id }}</b></span>
      <span class="fact"><i class="k">检查点数</i><b>{{ c.scene_count }}</b></span>
      <span class="fact diff"><i class="k">整体差异率</i>
        <b class="mono" :style="{ color: diffColor(c.diff_avg) }">{{ (c.diff_avg ?? 0).toFixed(2) }}%</b>
      </span>
      <a-button size="small" :loading="store.running" @click="rerun">
        {{ store.running && store.progress.total ? `重算中 ${store.progress.done}/${store.progress.total}` : '重新对比' }}
      </a-button>
    </div>
  </div>
</template>

<style scoped>
.summary {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 12px 8px 8px;
}

/* 触发器:把对比对做成可点击的历史切换入口 */
.pair-trigger {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; border-radius: 8px; cursor: pointer;
  border: 1px solid transparent; background: none; font-family: inherit;
  color: var(--color-text-1);
  transition: background-color .15s, border-color .15s;
}
.pair-trigger:hover { background: var(--color-fill-1); }
.pair-trigger.open { background: var(--color-fill-2); border-color: var(--color-border-2); }
.pair-trigger .caret { color: var(--color-text-3); transition: transform .15s; flex: 0 0 12px; }
.pair-trigger.open .caret { transform: rotate(180deg); }

.pair { display: flex; align-items: center; gap: 8px; font-size: 13px; flex-wrap: wrap; }
.role { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
.role-cur { background: rgba(var(--batch-cur), .16); color: rgb(var(--batch-cur)); }
.role-base { background: rgba(var(--batch-base), .16); color: rgb(var(--batch-base)); }
.br { font-size: 12px; }
.vs { font-size: 11px; font-weight: 700; color: var(--color-text-4); margin: 0 4px; }

.swap-btn {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--color-border-2); background: transparent;
  color: var(--color-text-2); transition: background-color .15s, color .15s;
}
.swap-btn:hover { background: var(--color-fill-2); color: rgb(var(--arcoblue-6)); }
.swap-btn:disabled { cursor: not-allowed; opacity: .5; }
.spacer { flex: 1; }
.facts { display: flex; align-items: center; gap: 18px; white-space: nowrap; }
.fact { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.fact .k { font-style: normal; font-size: 12px; color: var(--color-text-3); }
.fact b { font-weight: 600; }
.fact.diff b { font-size: 15px; }

/* 历史弹层 */
.hist-pop { width: 300px; }
.hist-head { padding: 4px 8px 6px; font-size: 12px; }
.hist-head .cap { color: var(--color-text-4); font-size: 11px; }
.hist-list { max-height: 320px; overflow-y: auto; }
.hist-item {
  display: block; width: 100%; text-align: left; cursor: pointer;
  border: 1px solid transparent; border-radius: 8px; background: none;
  padding: 8px 10px; margin-bottom: 2px; font-family: inherit;
}
.hist-item:hover { background: var(--color-fill-1); }
.hist-item.active { background: var(--color-fill-2); box-shadow: inset 2px 0 0 rgb(var(--arcoblue-6)); }
.row1 { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.row1 .cur { color: rgb(var(--batch-cur)); }
.row1 .ref { color: rgb(var(--batch-base)); }
.row1 .vs { color: var(--color-text-4); font-size: 11px; }
.row1 .diff { margin-left: auto; font-weight: 600; }
.scene { font-size: 13px; font-weight: 600; color: var(--color-text-1); margin-top: 4px; }
.meta { display: flex; align-items: center; gap: 5px; font-size: 11px; margin-top: 3px; flex-wrap: wrap; }
.meta .arrow, .meta .dot { color: var(--color-text-4); }
</style>
