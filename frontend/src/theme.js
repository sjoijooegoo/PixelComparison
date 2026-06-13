import { ref } from 'vue'

// 默认暗色:受众为美术同学,暗色界面看图不眩光、与 DCC 工具习惯一致
export const theme = ref(localStorage.getItem('pc-theme') || 'dark')

function apply() {
  if (theme.value === 'dark') document.body.setAttribute('arco-theme', 'dark')
  else document.body.removeAttribute('arco-theme')
}

export function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('pc-theme', theme.value)
  apply()
}

apply()
