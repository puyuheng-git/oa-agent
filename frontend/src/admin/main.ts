import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './theme.css'
import App from './App.vue'
import { auth } from './auth'
import { router } from './router'
import { setUnauthenticatedHandler } from '@/shared/http'

setUnauthenticatedHandler(() => {
  if (auth.me) {
    auth.me = null
    router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})

createApp(App).use(ElementPlus, { locale: zhCn }).use(router).mount('#app')
