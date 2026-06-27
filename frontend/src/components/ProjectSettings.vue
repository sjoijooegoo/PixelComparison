<script setup>
import { reactive, computed, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore, SHADING_QUALITY_OPTIONS } from '../store'

const store = useStore()

// 默认画质下拉:「全部画质」(-1) + 当前勾选为可见的画质档位(随复选框联动)
const defaultQualityOptions = computed(() => [
  { value: -1, label: '全部画质' },
  ...SHADING_QUALITY_OPTIONS.filter((o) => form.filter_shading_qualities.includes(o.value)),
])

const DEFAULTS = {
  pixel_diff_threshold: 8,
  fail_threshold: 2.0,
  warn_threshold: 0.3,
  heatmap_blur: 6,
  heatmap_sensitivity: 0.25,
  heatmap_method: 'enhanced',
  heatmap_norm_scale: 80.0,
  heatmap_gamma: 1.4,
  heatmap_density_radius: 16.0,
  heatmap_density_floor: 0.2,
  default_shading_quality: 5,
  default_date_range_days: 7,
  filter_shading_qualities: [5, 4, 3, 2, 1, 0],
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
  if (form.default_shading_quality !== -1
      && !form.filter_shading_qualities.includes(form.default_shading_quality)) {
    Message.info('默认画质不在所选画质内,将以「全部画质」生效')
  }
  saving.v = true
  try {
    await store.saveSettings({ ...form })
    sync()
    Message.success('已保存;算法配置对新对比生效,筛选默认值在下次进入或点「清空」时套用')
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
        <h2>项目设置</h2>
        <p>调整对比算法参数与筛选默认值</p>
      </div>

      <a-alert type="info" closable class="tip">
        对比算法配置仅对新发起的对比生效;已有对比结果如需套用新配置,可在「对比结果」页点「重新对比」。
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
            <label>渲染方法</label>
            <a-select v-model="form.heatmap_method" size="large">
              <a-option value="enhanced">增强(绝对幅度+密度门控,推荐)</a-option>
              <a-option value="legacy">传统(逐图峰值归一化)</a-option>
            </a-select>
            <span class="hint">增强:强化成片大改的区域感、抑制弱而散的噪声;传统:旧算法,每张图各自拉满量程</span>
          </div>
          <div class="field">
            <label>模糊半径</label>
            <a-input-number v-model="form.heatmap_blur" :min="0" :max="50" :step="1" size="large" />
            <span class="hint">高斯模糊半径,越大色块越连片(0 为不模糊)</span>
          </div>
          <div v-if="form.heatmap_method === 'legacy'" class="field">
            <label>灵敏度</label>
            <a-input-number v-model="form.heatmap_sensitivity" :min="0.01" :max="1" :step="0.05" :precision="2" size="large" />
            <span class="hint">归一化下限,越小越灵敏、越易显红(0.01–1)</span>
          </div>
          <template v-else>
            <div class="field">
              <label>绝对量程</label>
              <a-input-number v-model="form.heatmap_norm_scale" :min="4" :max="255" :step="4" size="large" />
              <span class="hint">差异除以此值再上色,越小越敏感(差异越易显红);典型 60–100</span>
            </div>
            <div class="field">
              <label>低端抑制 (gamma)</label>
              <a-input-number v-model="form.heatmap_gamma" :min="0.5" :max="4" :step="0.1" :precision="1" size="large" />
              <span class="hint">&gt;1 压低弱信号,弱散差异更冷;典型 1.2–2.0</span>
            </div>
            <div class="field">
              <label>密度门控半径</label>
              <a-input-number v-model="form.heatmap_density_radius" :min="0" :max="60" :step="2" size="large" />
              <span class="hint">判定「成片」的邻域尺度,越大越只保留大块连续差异(0 为关闭门控)</span>
            </div>
            <div class="field">
              <label>散点容忍下限</label>
              <a-input-number v-model="form.heatmap_density_floor" :min="0" :max="0.9" :step="0.05" :precision="2" size="large" />
              <span class="hint">邻域变化密度低于此值的散点被压暗,越大越只留密集区(0–0.9)</span>
            </div>
          </template>
        </div>
      </section>

      <!-- 筛选默认值 -->
      <section class="block">
        <div class="block-title">筛选默认值</div>
        <div class="grid grid-2">
          <div class="field field-full">
            <label>筛选框显示的画质</label>
            <a-checkbox-group v-model="form.filter_shading_qualities">
              <a-checkbox v-for="o in SHADING_QUALITY_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</a-checkbox>
            </a-checkbox-group>
            <span class="hint">勾选哪些画质会出现在筛选框的画质下拉里(至少勾一个;不勾任何项保存时回退为全部)</span>
          </div>
          <div class="field">
            <label>默认画质</label>
            <a-select v-model="form.default_shading_quality" size="large">
              <a-option v-for="o in defaultQualityOptions" :key="o.value" :value="o.value">{{ o.label }}</a-option>
            </a-select>
            <span class="hint">进入页面或点「清空」时,画质筛选默认选中此项(「全部画质」为不筛选)</span>
          </div>
          <div class="field">
            <label>默认日期范围(最近 N 天)</label>
            <a-input-number v-model="form.default_date_range_days" :min="1" :max="365" :step="1" size="large" />
            <span class="hint">进入页面或点「清空」时,创建时间默认为「今天往前 N 天」</span>
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
.field-full { grid-column: 1 / -1; }
.field label { font-size: 13px; color: var(--color-text-2); }
.field :deep(.arco-input-number) { width: 100%; }
.field .hint { font-size: 12px; color: var(--color-text-3); line-height: 1.5; }

.actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }
</style>
