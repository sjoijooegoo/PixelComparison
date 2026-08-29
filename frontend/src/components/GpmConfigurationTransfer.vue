<script setup>
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'

import { api } from '../api'
import { useGpmScaleConfigStore } from '../stores/gpmScaleConfigStore'

const configStore = useGpmScaleConfigStore()

const fileInput = ref(null)
const modalOpen = ref(false)
const exportModalOpen = ref(false)
const checking = ref(false)
const applying = ref(false)
const exportingScope = ref('')
const selectedName = ref('')
const report = ref(null)
const requestError = ref('')

const summaryCards = computed(() => {
  const summary = report.value?.summary
  if (!summary) return []
  return [
    { key: 'maps', label: '地图资源', ...summary.maps },
    { key: 'metric_scales', label: '指标标尺', ...summary.metric_scales },
    { key: 'scale_sets', label: '指标标尺集', ...summary.scale_sets },
    { key: 'map_bindings', label: '地图标尺关联', ...summary.map_bindings },
    {
      key: 'images', label: '地图图片', included: summary.images.included,
      total: summary.images.total,
      new: summary.images.added, updated: summary.images.replaced + summary.images.removed,
      unchanged: summary.images.unchanged,
    },
  ].filter((item) => item.included !== false)
})

const changedItems = computed(() => (
  report.value?.changes?.filter((item) => item.action !== 'unchanged') || []
))
const importNote = computed(() => ({
  maps: '只更新地图图片与坐标信息，现有标尺配置保持不变',
  scales: '只更新标尺及地图关联，现有地图图片与坐标保持不变',
}[report.value?.package?.scope] || '包中未出现的现有配置会继续保留'))

function actionLabel(action) {
  return action === 'new' ? '新增' : action === 'updated' ? '更新' : '不变'
}

function triggerImport() {
  if (checking.value || applying.value) return
  if (fileInput.value) fileInput.value.value = ''
  fileInput.value?.click()
}

async function inspectFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  selectedName.value = file.name
  report.value = null
  requestError.value = ''
  checking.value = true
  modalOpen.value = true
  try {
    report.value = await api.inspectGpmConfiguration(file)
  } catch (error) {
    requestError.value = error?.message || '配置包检查失败'
  } finally {
    checking.value = false
  }
}

async function exportConfiguration(scope) {
  exportingScope.value = scope
  try {
    const result = await api.exportGpmConfiguration(scope)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = result.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    exportModalOpen.value = false
    Message.success('热力图配置已导出')
  } catch (error) {
    Message.error(error?.message || '热力图配置导出失败')
  } finally {
    exportingScope.value = ''
  }
}

function closeModal() {
  if (!applying.value) modalOpen.value = false
}

async function applyImport() {
  if (!report.value?.valid || !report.value?.import_id) return
  applying.value = true
  requestError.value = ''
  try {
    await api.applyGpmConfigurationImport(report.value.import_id)
    Message.success('热力图配置已导入')
    modalOpen.value = false
    try {
      await configStore.load()
    } catch (error) {
      Message.error(error?.message || '配置已导入，但列表刷新失败')
    }
  } catch (error) {
    requestError.value = error?.message || '配置导入失败，请重新检查配置包'
    report.value = report.value ? {
      ...report.value,
      valid: false,
      import_id: null,
    } : null
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div class="configuration-transfer" role="group" aria-label="热力图配置导入导出">
    <input ref="fileInput" type="file" accept=".zip,application/zip" hidden @change="inspectFile">
    <a-tooltip content="导入热力图配置">
      <button class="icon-btn" aria-label="导入热力图配置"
        :disabled="checking || applying" @click="triggerImport">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 15V3" /><path d="m7 8 5-5 5 5" /><path d="M5 21h14" />
        </svg>
      </button>
    </a-tooltip>
    <a-tooltip content="导出热力图配置">
      <button class="icon-btn" aria-label="导出热力图配置"
        :disabled="Boolean(exportingScope)" @click="exportModalOpen = true">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" />
        </svg>
      </button>
    </a-tooltip>

    <a-modal :visible="exportModalOpen" :footer="false" :mask-closable="!exportingScope"
      :closable="!exportingScope" width="460px" modal-class="gpm-export-modal"
      @cancel="exportModalOpen = false">
      <template #title>导出热力图配置</template>
      <div class="export-options">
        <button :disabled="Boolean(exportingScope)" @click="exportConfiguration('all')">
          <strong>全部配置</strong><span>地图资源与标尺配置</span>
        </button>
        <button :disabled="Boolean(exportingScope)" @click="exportConfiguration('maps')">
          <strong>地图与图片</strong><span>图片、坐标范围与轴向</span>
        </button>
        <button :disabled="Boolean(exportingScope)" @click="exportConfiguration('scales')">
          <strong>标尺配置</strong><span>标尺、标尺集与地图关联</span>
        </button>
      </div>
    </a-modal>

    <a-modal :visible="modalOpen" :footer="false" :closable="!applying"
      :mask-closable="false" width="840px" modal-class="gpm-import-modal"
      @cancel="closeModal">
      <template #title>检查配置包</template>
      <div class="import-workspace">
        <div class="package-line">
          <div><span>配置包</span><strong :title="selectedName">{{ selectedName }}</strong></div>
          <a-button size="mini" type="text" :disabled="checking || applying" @click="triggerImport">
            重新选择
          </a-button>
        </div>

        <div v-if="checking" class="import-state"><a-spin /> 正在检查格式、引用和配置冲突…</div>
        <div v-else-if="requestError" class="import-error">{{ requestError }}</div>

        <template v-if="!checking && report">
          <div class="inspection-status" :class="{ invalid: !report.valid }">
            <span class="status-mark">{{ report.valid ? '✓' : '!' }}</span>
            <div>
              <strong>{{ report.valid ? '配置包检查通过' : '配置包不能应用' }}</strong>
              <span>{{ report.valid ? '未发现格式、引用或版本冲突' : `发现 ${report.issues.length} 个问题` }}</span>
            </div>
          </div>

          <div v-if="summaryCards.length" class="summary-strip">
            <article v-for="card in summaryCards" :key="card.key">
              <span>{{ card.label }}</span><strong>{{ card.total }}</strong>
              <small>
                <em v-if="card.new">新增 {{ card.new }}</em>
                <em v-if="card.updated">更新 {{ card.updated }}</em>
                <i v-if="!card.new && !card.updated">无变化</i>
              </small>
            </article>
          </div>

          <section v-if="report.issues?.length" class="inspection-section">
            <h4>需要处理</h4>
            <div class="issue-list">
              <div v-for="(issue, index) in report.issues" :key="`${issue.code}-${index}`">
                <strong>{{ issue.message }}</strong><span>{{ issue.scope }}</span>
              </div>
            </div>
          </section>

          <section v-else class="inspection-section">
            <h4>配置变更</h4>
            <div v-if="changedItems.length" class="change-list">
              <div v-for="item in changedItems" :key="`${item.kind}-${item.identity}`">
                <span class="change-badge" :class="item.action">{{ actionLabel(item.action) }}</span>
                <strong>{{ item.kind_label }} · {{ item.name }}</strong>
                <span>{{ item.details.join('、') }}</span>
              </div>
            </div>
            <div v-else class="no-changes">配置包与当前配置一致，应用后不会改变修订号。</div>
          </section>
        </template>
      </div>
      <footer class="import-footer">
        <span>{{ importNote }}</span>
        <div>
          <a-button size="small" :disabled="applying" @click="closeModal">取消</a-button>
          <a-button size="small" type="primary" :loading="applying"
            :disabled="!report?.valid || !report?.import_id" @click="applyImport">
            应用配置
          </a-button>
        </div>
      </footer>
    </a-modal>
  </div>
</template>

<style scoped>
.configuration-transfer { display: contents; }
.icon-btn {
  width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--color-border-2); background: transparent;
  color: var(--color-text-2); display: flex; align-items: center; justify-content: center;
}
.icon-btn:hover:not(:disabled) { background: var(--color-fill-2); color: var(--color-text-1); }
.icon-btn:disabled { cursor: not-allowed; opacity: .5; }
.export-options { display: grid; gap: 7px; }
.export-options button {
  min-height: 52px; padding: 8px 11px; display: flex; align-items: center;
  justify-content: space-between; gap: 16px; border: 1px solid var(--color-border-1);
  border-radius: 5px; background: var(--color-fill-1); color: inherit; cursor: pointer;
  font: inherit; text-align: left;
}
.export-options button:hover:not(:disabled) {
  border-color: rgba(var(--arcoblue-5), .55); background: var(--color-fill-2);
}
.export-options button:disabled { cursor: wait; opacity: .58; }
.export-options strong { color: var(--color-text-1); font-size: 12px; font-weight: 600; }
.export-options span { color: var(--color-text-4); font-size: 10px; }
.import-workspace { min-height: 310px; max-height: min(68vh, 650px); overflow: auto; }
.package-line {
  min-height: 42px; padding: 0 10px; display: flex; align-items: center; justify-content: space-between;
  border: 1px solid var(--color-border-1); border-radius: 5px; background: var(--color-fill-1);
}
.package-line > div { min-width: 0; display: flex; align-items: center; gap: 10px; }
.package-line span { flex: 0 0 auto; color: var(--color-text-4); font-size: 11px; }
.package-line strong { overflow: hidden; color: var(--color-text-1); font-size: 12px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.import-state { min-height: 230px; display: flex; align-items: center; justify-content: center; gap: 10px; color: var(--color-text-3); }
.import-error { margin-top: 12px; padding: 12px; border: 1px solid rgba(var(--red-6), .35); border-radius: 5px; color: rgb(var(--red-6)); background: rgba(var(--red-6), .07); }
.inspection-status { margin-top: 12px; padding: 11px 12px; display: flex; align-items: center; gap: 10px; border: 1px solid rgba(var(--green-6), .32); border-radius: 5px; background: rgba(var(--green-6), .07); }
.inspection-status.invalid { border-color: rgba(var(--red-6), .35); background: rgba(var(--red-6), .07); }
.status-mark { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 50%; color: rgb(var(--green-6)); background: rgba(var(--green-6), .14); font-size: 14px; font-weight: 700; }
.invalid .status-mark { color: rgb(var(--red-6)); background: rgba(var(--red-6), .14); }
.inspection-status > div { display: grid; gap: 2px; }
.inspection-status strong { color: var(--color-text-1); font-size: 13px; }
.inspection-status div span { color: var(--color-text-3); font-size: 11px; }
.summary-strip { margin-top: 10px; display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 8px; }
.summary-strip article { min-width: 0; padding: 9px 10px; border: 1px solid var(--color-border-1); border-radius: 5px; background: var(--color-fill-1); }
.summary-strip article > span { color: var(--color-text-3); font-size: 10px; }
.summary-strip article > strong { display: block; margin: 2px 0 3px; color: var(--color-text-1); font-size: 19px; font-variant-numeric: tabular-nums; }
.summary-strip small { display: flex; gap: 7px; font-size: 10px; font-style: normal; }
.summary-strip em { color: rgb(var(--arcoblue-6)); font-style: normal; }
.summary-strip i { color: var(--color-text-4); font-style: normal; }
.inspection-section { margin-top: 14px; }
.inspection-section h4 { margin: 0 0 7px; color: var(--color-text-2); font-size: 12px; }
.change-list, .issue-list { border: 1px solid var(--color-border-1); border-radius: 5px; overflow: hidden; }
.change-list > div, .issue-list > div { min-height: 38px; padding: 6px 10px; display: grid; align-items: center; gap: 8px; border-bottom: 1px solid var(--color-border-1); }
.change-list > div { grid-template-columns: 42px minmax(180px, .8fr) minmax(180px, 1.2fr); }
.issue-list > div { grid-template-columns: minmax(240px, 1fr) minmax(180px, .7fr); }
.change-list > div:last-child, .issue-list > div:last-child { border-bottom: 0; }
.change-list strong, .issue-list strong { overflow: hidden; color: var(--color-text-2); font-size: 11px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.change-list > div > span:last-child, .issue-list span { color: var(--color-text-4); font-size: 10px; }
.change-badge { width: 36px; padding: 2px 0; border-radius: 3px; text-align: center; }
.change-badge.new { color: rgb(var(--green-6)); background: rgba(var(--green-6), .11); }
.change-badge.updated { color: rgb(var(--arcoblue-6)); background: rgba(var(--arcoblue-6), .11); }
.no-changes { min-height: 70px; display: flex; align-items: center; justify-content: center; border: 1px dashed var(--color-border-2); border-radius: 5px; color: var(--color-text-4); font-size: 11px; }
.import-footer { padding-top: 12px; display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--color-border-1); }
.import-footer > span { color: var(--color-text-4); font-size: 10px; }
.import-footer > div { display: flex; gap: 8px; }
</style>
