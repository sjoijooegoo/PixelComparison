<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useStore } from '../store'

const store = useStore()
const metrics = computed(() => store.detail?.metrics)
const histMode = ref('RGB')
const histCanvas = ref(null)

const rows = computed(() => {
  const m = metrics.value
  if (!m) return []
  return [
    ['差异像素数', m.diff_pixels.toLocaleString()],
    ['总像素数', m.total_pixels.toLocaleString()],
    ['最大差异(单像素)', m.max_diff],
    ['平均差异(仅差异区域)', m.mean_diff_changed],
    ['RMS', m.rms],
    ['SSIM', m.ssim],
    ['PSNR', m.psnr + ' dB'],
  ]
})

const HERO_COLOR = {
  fail: 'rgb(var(--red-6))',
  warn: 'rgb(var(--orange-6))',
  pass: 'rgb(var(--green-6))',
}

const CH_COLORS = { R: '#f53f3f', G: '#00b42a', B: '#165dff' }

function drawHist() {
  const cv = histCanvas.value
  const m = metrics.value
  if (!cv || !m) return
  const ctx = cv.getContext('2d')
  const { width: w, height: h } = cv
  ctx.clearRect(0, 0, w, h)

  const chans = histMode.value === 'RGB' ? [0, 1, 2] : [{ R: 0, G: 1, B: 2 }[histMode.value]]
  const fills = ['rgba(245,63,63,.45)', 'rgba(0,180,42,.45)', 'rgba(22,93,255,.45)']
  const maxVal = Math.max(...chans.flatMap(c => m.hist_current[c]), 1)

  for (const c of chans) {
    // 当前版本:填充
    const bins = m.hist_current[c]
    ctx.fillStyle = fills[c]
    ctx.beginPath()
    ctx.moveTo(0, h)
    bins.forEach((v, i) => ctx.lineTo((i / (bins.length - 1)) * w, h - (v / maxVal) * h * 0.92))
    ctx.lineTo(w, h)
    ctx.closePath()
    ctx.fill()
    // 基线版本:虚线轮廓
    const base = m.hist_baseline[c]
    ctx.strokeStyle = fills[c].replace('.45', '.9')
    ctx.setLineDash([3, 3])
    ctx.beginPath()
    base.forEach((v, i) => {
      const x = (i / (base.length - 1)) * w
      const y = h - (v / maxVal) * h * 0.92
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.stroke()
    ctx.setLineDash([])
  }
}

watch([metrics, histMode], () => requestAnimationFrame(drawHist))
onMounted(drawHist)
</script>

<template>
  <aside class="metrics panel-border-l">
    <template v-if="metrics">
      <div class="hero">
        <div class="hero-label text-secondary">差异率(像素)</div>
        <div class="hero-value mono" :style="{ color: HERO_COLOR[store.detail.status] || 'var(--color-text-1)' }">
          {{ metrics.diff_pct.toFixed(2) }}<span class="hero-unit">%</span>
        </div>
      </div>
      <a-collapse :default-active-key="['overall', 'hist']" :bordered="false">
        <a-collapse-item header="总体指标" key="overall">
          <div v-for="[k, v, bad] in rows" :key="k" class="row">
            <span class="text-secondary">{{ k }}</span>
            <span class="mono" :class="{ 'diff-fail': bad }">{{ v }}</span>
          </div>
        </a-collapse-item>

        <a-collapse-item header="通道差异" key="channel">
          <div v-for="(v, ch) in metrics.channel_diff" :key="ch" class="row">
            <span style="width: 18px">{{ ch }}</span>
            <a-progress :percent="Math.min(1, v / 10)" :show-text="false" size="small"
              :color="CH_COLORS[ch]" style="flex: 1; margin: 0 8px" />
            <span class="mono">{{ v.toFixed(2) }}%</span>
          </div>
        </a-collapse-item>

        <a-collapse-item header="直方图对比" key="hist">
          <a-select v-model="histMode" size="mini" style="width: 80px; margin-bottom: 8px">
            <a-option>RGB</a-option><a-option>R</a-option><a-option>G</a-option><a-option>B</a-option>
          </a-select>
          <canvas ref="histCanvas" width="190" height="120" class="hist"></canvas>
          <div class="text-secondary" style="font-size: 11px">实线填充 = 当前版本,虚线 = 基线</div>
        </a-collapse-item>
      </a-collapse>
    </template>
    <a-empty v-else-if="store.detail" description="该场景无对比指标" style="margin-top: 40px" />
  </aside>
</template>

<style scoped>
.metrics { width: 400px; flex: 0 0 400px; overflow-y: auto; min-height: 0; }
.hero { padding: 16px 16px 12px; border-bottom: 1px solid var(--color-border-1); }
.hero-label { font-size: 12px; margin-bottom: 2px; }
.hero-value { font-size: 26px; font-weight: 700; line-height: 1.2; letter-spacing: -.5px; }
.hero-unit { font-size: 15px; font-weight: 600; margin-left: 1px; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; font-size: 12px; }
.hist { width: 100%; height: 120px; background: var(--color-fill-1); border-radius: 6px; }
:deep(.arco-collapse-item-header) { font-weight: 600; }
</style>
