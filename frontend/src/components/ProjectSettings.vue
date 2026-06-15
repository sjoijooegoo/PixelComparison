<script setup>
import { reactive, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore } from '../store'

const store = useStore()

const DEFAULTS = {
  pixel_diff_threshold: 8,
  fail_threshold: 2.0,
  warn_threshold: 0.3,
  heatmap_blur: 6,
  heatmap_sensitivity: 0.25,
}

const form = reactive({ ...DEFAULTS })
const saving = reactive({ v: false })

function sync() { Object.assign(form, store.settings) }

onMounted(async () => {
  await store.loadSettings()
  sync()
})

async function save() {
  if (form.warn_threshold > form.fail_threshold) {
    Message.warning('橙色阈值不能大于红色阈值')
    return
  }
  saving.v = true
  try {
    await store.saveSettings({ ...form })
    sync()
    Message.success('已保存,新发起的对比将使用该配置')
  } catch (e) {
    Message.error(e.message || '保存失败')
  } finally {
    saving.v = false
  }
}

function resetDefaults() { Object.assign(form, DEFAULTS) }
</script>

<template>
  <div class="settings-page">
    <div class="inner">
      <div class="page-head">
        <h2>对比算法配置</h2>
        <p>调整差异判定与热力图渲染参数</p>
      </div>

      <a-alert type="info" closable class="tip">
        配置仅对新发起的对比生效;已有对比结果如需套用新配置,可在「对比结果」页点「重新对比」。
      </a-alert>

      <!-- 差异判定 -->
      <section class="block">
        <div class="block-title">差异判定</div>
        <div class="grid grid-3">
          <div class="field">
            <label>像素差异阈值</label>
            <a-input-number v-model="form.pixel_diff_threshold" :min="0" :max="255" :step="1" size="large" />
            <span class="hint">单像素通道差超过此值才算「变化像素」,直接影响差异率</span>
          </div>
          <div class="field">
            <label>差异率红色阈值 (%)</label>
            <a-input-number v-model="form.fail_threshold" :min="0" :max="100" :step="0.1" :precision="2" size="large" />
            <span class="hint">差异率 ≥ 此值显示为红色(高差异)</span>
          </div>
          <div class="field">
            <label>差异率橙色阈值 (%)</label>
            <a-input-number v-model="form.warn_threshold" :min="0" :max="100" :step="0.1" :precision="2" size="large" />
            <span class="hint">差异率 ≥ 此值显示为橙色(中等差异)</span>
          </div>
        </div>
      </section>

      <!-- 热力图渲染 -->
      <section class="block">
        <div class="block-title">热力图渲染</div>
        <div class="grid grid-2">
          <div class="field">
            <label>模糊半径</label>
            <a-input-number v-model="form.heatmap_blur" :min="0" :max="50" :step="1" size="large" />
            <span class="hint">高斯模糊半径,越大色块越连片(0 为不模糊)</span>
          </div>
          <div class="field">
            <label>灵敏度</label>
            <a-input-number v-model="form.heatmap_sensitivity" :min="0.01" :max="1" :step="0.05" :precision="2" size="large" />
            <span class="hint">归一化下限,越小越灵敏、越易显红(0.01–1)</span>
          </div>
        </div>
      </section>

      <div class="actions">
        <a-button size="large" @click="resetDefaults">恢复默认</a-button>
        <a-button type="primary" size="large" :loading="saving.v" @click="save">保存</a-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page { flex: 1; overflow-y: auto; padding: 28px 32px; }
.inner { max-width: 1360px; margin: 0 auto; }

.page-head { margin-bottom: 20px; }
.page-head h2 { margin: 0; font-size: 24px; font-weight: 700; letter-spacing: .5px; }
.page-head p { margin: 6px 0 0; font-size: 13px; color: var(--color-text-3); }

.tip { margin-bottom: 18px; border-radius: 8px; }

/* 分区块 */
.block {
  background: var(--color-fill-1);
  border: 1px solid var(--color-border-2);
  border-radius: 12px;
  padding: 20px 24px 24px;
  margin-bottom: 18px;
}
.block-title {
  font-size: 15px; font-weight: 600; color: var(--color-text-1);
  padding-left: 10px; margin-bottom: 20px;
  border-left: 3px solid rgb(var(--arcoblue-6));
}

.grid { display: grid; gap: 22px 28px; }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-2 { grid-template-columns: repeat(2, 1fr); }

.field { display: flex; flex-direction: column; gap: 9px; min-width: 0; }
.field label { font-size: 13px; color: var(--color-text-2); }
.field :deep(.arco-input-number) { width: 100%; }
.field .hint { font-size: 12px; color: var(--color-text-3); line-height: 1.5; }

.actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }
</style>
