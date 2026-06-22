<script setup>
import { onMounted } from 'vue'
import { useStore } from './store'
import TopBar from './components/TopBar.vue'
import ManualUpload from './components/ManualUpload.vue'

const store = useStore()

onMounted(() => store.init())
</script>

<template>
  <div class="app-layout">
    <TopBar />
    <!-- 缓存批次管理(列表图 DOM 较重):切到对比/设置再切回时不重建,避免明显卡顿 -->
    <router-view v-slot="{ Component }">
      <keep-alive :include="['BatchView']">
        <component :is="Component" />
      </keep-alive>
    </router-view>

    <!-- 手动上报弹窗(由顶栏按钮触发,全局挂载) -->
    <ManualUpload v-model:visible="store.uploadVisible" @done="store.refreshBatches()" />
  </div>
</template>
