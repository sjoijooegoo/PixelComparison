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
    <router-view />

    <!-- 手动上报弹窗(由顶栏按钮触发,全局挂载) -->
    <ManualUpload v-model:visible="store.uploadVisible" @done="store.refreshBatches()" />
  </div>
</template>
