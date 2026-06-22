<script setup>
import { ref, reactive } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { api } from '../api'
import { p4Label } from '../store'

const props = defineProps({ visible: { type: Boolean, default: false } })
const emit = defineEmits(['update:visible', 'done'])

const stage = ref('idle')        // idle | preview | uploading
const dragOver = ref(false)
const error = ref('')
const autoCompare = ref(true)
const idExists = ref(false)      // 该批次 ID 是否已存在(重复上报会变成补传/合并)
const overwrite = ref(false)     // 同号批次已存在时:勾选则删旧建新
const fileInput = ref(null)
const manualP4 = ref(null)       // 数据包未带 P4 时,用户手填的版本号

// 解析结果
const parsed = reactive({ body: null, shots: [], missing: [] })
const progress = reactive({ done: 0, total: 0 })

function reset() {
  stage.value = 'idle'
  error.value = ''
  idExists.value = false
  overwrite.value = false
  parsed.body = null
  parsed.shots = []
  parsed.missing = []
  manualP4.value = null
  progress.done = 0
  progress.total = 0
}

function close() {
  if (stage.value === 'uploading') return   // 上报中不允许关闭
  emit('update:visible', false)
  reset()
}

// ---- 收集文件夹内全部文件 -> Map<相对路径, File> ----
function readEntry(entry, prefix, map) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => { map.set(prefix + entry.name, file); resolve() }, () => resolve())
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      const readChunk = () => reader.readEntries(async (entries) => {
        if (!entries.length) return resolve()
        await Promise.all(entries.map((e) => readEntry(e, prefix + entry.name + '/', map)))
        readChunk()   // readEntries 分批返回,需循环读到空
      }, () => resolve())
      readChunk()
    } else resolve()
  })
}

async function onDrop(e) {
  dragOver.value = false
  const entries = [...(e.dataTransfer?.items || [])]
    .map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry())
    .filter(Boolean)
  if (!entries.length) { error.value = '请拖入一个文件夹(需包含 manifest.json)'; return }
  const map = new Map()
  for (const ent of entries) await readEntry(ent, '', map)
  parsePackage(map)
}

function onPick(e) {
  const files = [...(e.target.files || [])]
  if (!files.length) return
  const map = new Map()
  for (const f of files) map.set(f.webkitRelativePath || f.name, f)
  parsePackage(map)
  e.target.value = ''   // 允许重复选择同一文件夹
}

// ---- 解析 manifest,对齐 report.py 的字段映射 ----
async function parsePackage(map) {
  reset()
  try {
    // 找最浅的 manifest.json
    let manifestKey = null
    for (const key of map.keys()) {
      if (key.split('/').pop() === 'manifest.json') {
        if (!manifestKey || key.split('/').length < manifestKey.split('/').length) manifestKey = key
      }
    }
    if (!manifestKey) { error.value = '未找到 manifest.json,请拖入正确的数据包文件夹'; return }
    const manifestDir = manifestKey.slice(0, manifestKey.length - 'manifest.json'.length)
    const manifest = JSON.parse(await map.get(manifestKey).text())

    const pipeline = manifest.pipeline_data || {}
    const ue = manifest.ue_data || {}
    const res = ue.resolution || {}
    const resolution = res.width && res.height ? `${res.width}x${res.height}` : null
    const batchId = pipeline.id ?? pipeline.batch_id
    const p4raw = ue.p4_version
    const p4 = (p4raw === undefined || p4raw === null || p4raw === '') ? null : parseInt(p4raw, 10)
    parsed.body = {
      id: batchId != null ? String(batchId) : null,
      scene_id: ue.world_name,
      p4_version: Number.isNaN(p4) ? null : p4,   // 未上报 p4 则留空
      platform: ue.platform,
      creator: manifest.creator || '手动上报',
      batch_url: pipeline.url || pipeline.batch_url || null,
      resolution,
      capture_type: manifest.capture_type ?? null,
      levelsequence_name: ue.levelsequence_name ?? null,
      levelsequence_path: ue.levelsequence_path ?? null,
      shading_quality: ue.shading_quality ?? null,
      captured_at: pipeline.captured_at ?? null,
    }
    if (!parsed.body.scene_id || !parsed.body.platform) {
      error.value = 'manifest 缺少必要字段(world_name / platform)'
      parsed.body = null
      return
    }

    for (const s of manifest.screenshots || []) {
      const rel = (s.image || '').replace(/\\/g, '/')
      const file = map.get(manifestDir + rel)
      if (file) parsed.shots.push({ name: s.name, file, camera: s.camera, index: s.index })
      else parsed.missing.push(s.image || s.name)
    }
    if (!parsed.shots.length) { error.value = '数据包内没有可上传的截图'; parsed.body = null; return }

    // 未带批次号 -> 后端上报时自动生成,无需查重;带了才检测是否已存在
    if (parsed.body.id) {
      try {
        const { items } = await api.batches({ q: parsed.body.id })
        idExists.value = items.some((b) => String(b.id) === String(parsed.body.id))
      } catch { idExists.value = false }
    }

    stage.value = 'preview'
  } catch (e) {
    error.value = '解析失败:' + (e.message || e)
  }
}

// 点击「开始上报」:ID 已存在则先弹确认,说明会变成补传/合并
function onStart() {
  if (idExists.value) {
    const content = overwrite.value
      ? `将删除批次 #${parsed.body.id} 的旧截图与其对比记录(及热力图)并用本次数据重建。是否继续?`
      : '该批次号已存在,继续不会新建批次,而是把截图补传/合并进已有批次(同名截图会跳过)。是否继续?'
    Modal.confirm({
      title: `批次 #${parsed.body.id} 已存在`,
      content,
      okText: overwrite.value ? '覆盖重建' : '继续上报',
      cancelText: '取消',
      onOk: () => startUpload(),
    })
  } else {
    startUpload()
  }
}

// 单张截图上传:最多 3 次机会。网络错误/5xx 视为偶发,重试(退避);
// 409=已存在按"跳过"原样抛出;其他 4xx 重试无意义,直接抛。
async function uploadShot(batchId, s, attempts = 3) {
  for (let i = 1; i <= attempts; i++) {
    const fd = new FormData()
    fd.append('scene_name', s.name)
    if (s.camera != null) fd.append('camera', JSON.stringify(s.camera))
    if (s.index != null) fd.append('frame_index', String(s.index))
    fd.append('file', s.file, s.file.name)
    try {
      return await api.uploadScreenshot(batchId, fd, { sceneName: s.name, fileName: s.file.name })
    } catch (e) {
      const transient = !e.status || e.status >= 500
      if (e.status === 409 || !transient || i === attempts) throw e
      await new Promise((r) => setTimeout(r, 300 * i))   // 退避 300/600ms 后重试
    }
  }
}

// ---- 执行上报,流程对齐 report.py ----
async function startUpload() {
  // 数据包未带 P4 时,采用用户手填的版本号(选填)
  if (parsed.body.p4_version == null && manualP4.value != null && manualP4.value !== '') {
    parsed.body.p4_version = Number(manualP4.value)
  }
  parsed.body.overwrite = overwrite.value   // 同号覆盖:后端删旧建新
  stage.value = 'uploading'
  progress.done = 0
  progress.total = parsed.shots.length
  let batchId = parsed.body.id
  try {
    try {
      const created = await api.createBatch(parsed.body)
      batchId = created.id   // 后端可能自动生成批次号,以返回值为准
    } catch (e) {
      if (e.status !== 409) throw e   // 409=已存在(未勾覆盖),沿用原 id 继续补传
    }

    let failed = 0
    for (const s of parsed.shots) {
      try {
        await uploadShot(batchId, s)
      } catch (e) {
        if (e.status !== 409) { failed++; console.warn('上传失败(已重试 3 次)', s.name, e) }
      }
      progress.done++
    }

    let compMsg = ''
    if (autoCompare.value && !failed) {
      try {
        const r = await api.autoCompare(batchId)
        compMsg = r?.matched ? `,已与 #${r.ref_batch_id} 发起对比` : ',无同类历史批次,未对比'
      } catch { /* 自动对比失败忽略 */ }
    }

    if (failed) Message.warning(`批次 #${batchId} 上报完成,但有 ${failed} 张失败`)
    else Message.success(`批次 #${batchId} 上报成功(${progress.total} 张)${compMsg}`)
    emit('done')
    emit('update:visible', false)
    reset()
  } catch (e) {
    Message.error(e.message || '上报失败')
    stage.value = 'preview'
  }
}
</script>

<template>
  <a-modal :visible="visible" @update:visible="close" :footer="false" width="560px"
    title-align="start" :mask-closable="stage !== 'uploading'" :closable="stage !== 'uploading'">
    <template #title>手动上报</template>

    <!-- 拖拽 / 选择 -->
    <div v-if="stage === 'idle'">
      <div class="drop" :class="{ over: dragOver }"
        @dragover.prevent="dragOver = true" @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop" @click="fileInput.click()">
        <div class="big">＋</div>
        <div>把 <b>PixelComparison</b> 数据包文件夹拖到这里</div>
        <div class="sub">或点击选择文件夹 · 需包含 manifest.json 与 Screenshot/</div>
      </div>
      <input ref="fileInput" type="file" webkitdirectory directory multiple
        style="display:none" @change="onPick" />
      <a-alert v-if="error" type="error" style="margin-top:12px">{{ error }}</a-alert>
    </div>

    <!-- 预览 -->
    <div v-else-if="stage === 'preview'">
      <a-descriptions :column="1" size="small" bordered :label-style="{ width: '72px' }" :data="[
        { label: '批次号', value: parsed.body.id ? ('#' + parsed.body.id) : '上报时自动生成' },
        { label: '场景ID', value: parsed.body.scene_id },
        { label: '平台', value: parsed.body.platform },
        { label: 'P4版本', value: p4Label(parsed.body.p4_version) },
        { label: '分辨率', value: parsed.body.resolution || '—' },
      ]">
        <template #value="{ data }">
          <a-input-number v-if="data.label === 'P4版本' && parsed.body.p4_version == null"
            v-model="manualP4" placeholder="数据包未带,可手动填写(选填)"
            :min="0" :precision="0" hide-button allow-clear size="small" style="width: 100%" />
          <span v-else>{{ data.value }}</span>
        </template>
      </a-descriptions>
      <div class="count">
        共 <b>{{ parsed.shots.length }}</b> 张截图
        <span v-if="parsed.missing.length" class="miss">(缺失 {{ parsed.missing.length }} 张,将跳过)</span>
      </div>
      <a-alert v-if="idExists" type="warning" style="margin-top:12px">
        批次 <b>#{{ parsed.body.id }}</b> 已存在!默认会把截图补传/合并进该批次(同名截图跳过);
        勾选下方「覆盖」则删除旧数据后重建。
      </a-alert>
      <a-checkbox v-if="idExists" v-model="overwrite" style="margin-top:10px; display:block; color: rgb(var(--red-6))">
        覆盖同号批次(删除旧截图与其对比/热力图后重建)
      </a-checkbox>
      <a-checkbox v-model="autoCompare" style="margin-top:10px">上传完成后自动对比(同场景+平台+画质的最新历史批次)</a-checkbox>
      <div class="actions">
        <a-button @click="reset">重新选择</a-button>
        <a-button type="primary" @click="onStart">开始上报</a-button>
      </div>
    </div>

    <!-- 上报中 -->
    <div v-else class="uploading">
      <div>正在上报批次 <b>#{{ parsed.body.id }}</b> …</div>
      <a-progress :percent="progress.total ? progress.done / progress.total : 0"
        :status="progress.done === progress.total ? 'success' : 'normal'" style="margin-top:12px" />
      <div class="count">{{ progress.done }} / {{ progress.total }} 张</div>
    </div>
  </a-modal>
</template>

<style scoped>
.drop {
  border: 2px dashed var(--color-border-3); border-radius: 10px;
  padding: 36px 16px; text-align: center; cursor: pointer;
  color: var(--color-text-2); transition: border-color .15s, background-color .15s;
}
.drop:hover, .drop.over { border-color: rgb(var(--arcoblue-6)); background: var(--color-fill-1); }
.drop .big { font-size: 34px; color: var(--color-text-3); line-height: 1; margin-bottom: 8px; }
.drop .sub { font-size: 12px; color: var(--color-text-3); margin-top: 6px; }
.count { margin-top: 12px; font-size: 13px; }
.count .miss { color: rgb(var(--orange-6)); margin-left: 6px; }
.actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.uploading { padding: 12px 0; }
</style>
