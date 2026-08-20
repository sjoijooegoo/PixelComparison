<script setup>
import { useProjectStore } from './stores/projectStore'
import TopBar from './components/TopBar.vue'
import ManualUpload from './components/ManualUpload.vue'
import { runPageRefresh } from './pageActions'

const store = useProjectStore()

async function refreshAfterUpload() {
  try {
    await store.loadMeta()
    await runPageRefresh({ refreshMeta: false })
  } catch {
    // 上报已经成功；刷新失败由当前页面的错误态和手动刷新继续承接。
  }
}
</script>

<template>
  <a-config-provider update-at-scroll>
    <div class="app-layout">
      <TopBar />
      <div v-if="store.initializing" class="startup-progress" aria-label="正在初始化">
        <span></span>
      </div>
      <!-- 只缓存截图对比工作区的重型网格 DOM。 -->
      <router-view v-slot="{ Component }">
        <keep-alive :include="['ScreenshotComparisonView']">
          <component :is="Component" />
        </keep-alive>
      </router-view>

      <!-- 手动上报弹窗(由顶栏按钮触发,全局挂载) -->
      <ManualUpload v-model:visible="store.uploadVisible" @done="refreshAfterUpload" />
    </div>
  </a-config-provider>
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
