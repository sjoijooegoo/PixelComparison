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
    <div class="card panel">
      <div class="head">
        <b>对比算法配置</b>
        <span class="text-secondary">调整差异判定与热力图渲染参数</span>
      </div>

      <a-alert type="info" style="margin: 0 0 16px">
        配置仅对新发起的对比生效;已有对比结果如需套用新配置,可在「对比结果」页点「重新对比」。
      </a-alert>

      <div class="group-title">差异判定</div>
      <div class="grid">
        <a-form-item label="像素差异阈值" help="单像素通道差超过此值才算「变化像素」,直接影响差异率">
          <a-input-number v-model="form.pixel_diff_threshold" :min="0" :max="255" :step="1" />
        </a-form-item>
        <a-form-item label="差异率红色阈值 (%)" help="差异率 ≥ 此值显示为红色(高差异)">
          <a-input-number v-model="form.fail_threshold" :min="0" :max="100" :step="0.1" :precision="2" />
        </a-form-item>
        <a-form-item label="差异率橙色阈值 (%)" help="差异率 ≥ 此值显示为橙色(中等差异)">
          <a-input-number v-model="form.warn_threshold" :min="0" :max="100" :step="0.1" :precision="2" />
        </a-form-item>
      </div>

      <div class="group-title">热力图渲染</div>
      <div class="grid">
        <a-form-item label="模糊半径" help="高斯模糊半径,越大色块越连片(0 为不模糊)">
          <a-input-number v-model="form.heatmap_blur" :min="0" :max="50" :step="1" />
        </a-form-item>
        <a-form-item label="灵敏度" help="归一化下限,越小越灵敏、越易显红(0.01–1)">
          <a-input-number v-model="form.heatmap_sensitivity" :min="0.01" :max="1" :step="0.05" :precision="2" />
        </a-form-item>
      </div>

      <div class="actions">
        <a-button @click="resetDefaults">恢复默认</a-button>
        <a-button type="primary" :loading="saving.v" @click="save">保存</a-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page { flex: 1; overflow-y: auto; padding: 16px; }
.panel { max-width: 720px; margin: 0 auto; padding: 18px 20px; }
.head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
.head b { font-size: 15px; }
.head span { font-size: 12px; }
.group-title {
  font-size: 13px; font-weight: 600; color: var(--color-text-2);
  margin: 6px 0 10px; padding-left: 8px; border-left: 3px solid rgb(var(--arcoblue-6));
}
.grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 24px; margin-bottom: 18px;
}
.grid :deep(.arco-input-number) { width: 160px; }
.actions { display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid var(--color-border-2); padding-top: 16px; }
</style>
