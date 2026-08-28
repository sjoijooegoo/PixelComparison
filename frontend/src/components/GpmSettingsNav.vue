<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const query = computed(() => (
  route.query.return_to ? { return_to: route.query.return_to } : {}
))
</script>

<template>
  <header class="settings-heading">
    <div class="heading-main">
      <nav aria-label="热力图设置页面">
        <router-link :to="{ path: '/settings/gpm-heatmap', query }">地图资源</router-link>
        <router-link :to="{ path: '/settings/gpm-heatmap/scales', query }">颜色标尺</router-link>
      </nav>
    </div>
    <div class="heading-actions"><slot /></div>
  </header>
</template>

<style scoped>
.settings-heading {
  min-height: 36px; display: flex; align-items: center; justify-content: space-between; gap: 20px;
}
.heading-main { min-width: 0; display: flex; align-items: center; }
nav {
  height: 32px; padding: 3px; display: flex; align-items: center; gap: 2px;
  border: 1px solid var(--color-border-1); border-radius: 5px; background: var(--color-fill-1);
}
nav a {
  height: 24px; padding: 0 12px; border-radius: 3px; display: inline-flex; align-items: center;
  color: var(--color-text-3); font-size: 11px; text-decoration: none;
}
nav a:hover { color: var(--color-text-1); background: var(--color-fill-2); }
nav a.router-link-exact-active {
  color: rgb(var(--arcoblue-6)); background: color-mix(in srgb, rgb(var(--arcoblue-6)) 13%, var(--color-fill-2));
}
.heading-actions { display: flex; align-items: center; gap: 8px; }
@media (max-width: 720px) {
  .settings-heading { align-items: center; }
}
</style>
