<script setup>
import { useStore } from './store'
import TopBar from './components/TopBar.vue'
import ManualUpload from './components/ManualUpload.vue'

const store = useStore()

function refreshAfterUpload() {
  store.refreshBatches().catch(() => {})
}
</script>

<template>
  <div class="app-layout">
    <TopBar />
    <div v-if="store.initializing" class="startup-progress" aria-label="正在初始化">
      <span></span>
    </div>
    <!-- 缓存批次管理(列表图 DOM 较重):切到对比/设置再切回时不重建,避免明显卡顿 -->
    <router-view v-slot="{ Component }">
      <keep-alive :include="['BatchView']">
        <component :is="Component" />
      </keep-alive>
    </router-view>

    <!-- 手动上报弹窗(由顶栏按钮触发,全局挂载) -->
    <ManualUpload v-model:visible="store.uploadVisible" @done="refreshAfterUpload" />
  </div>
</template>

<style scoped>
.startup-progress {
  position: fixed; top: 51px; left: 0; right: 0; z-index: 1000;
  height: 2px; overflow: hidden; pointer-events: none;
}
.startup-progress span {
  display: block; width: 34%; height: 100%; background: rgb(var(--arcoblue-6));
  animation: startup-slide 1.1s ease-in-out infinite;
}
@keyframes startup-slide {
  from { transform: translateX(-110%); }
  to { transform: translateX(400%); }
}
</style>
