import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElMessage } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import './styles/theme.css'
import './styles/react-bits.css'
import App from './App.vue'
import router from './router'
import { setupDirectives } from './directives/permission'

const app = createApp(App)

let lastGlobalErrorAt = 0

// Global Vue runtime error guard. Axios/request errors are handled by request.js
// or by the caller; do not show them as generic page crashes.
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', err, '\nInfo:', info)
  if (err?.isAxiosError || err?.name === 'AxiosError') return
  if (err && err.message && err.message.includes('Network')) return

  const now = Date.now()
  if (now - lastGlobalErrorAt > 3000) {
    lastGlobalErrorAt = now
    ElMessage.error('\u9875\u9762\u8fd0\u884c\u51fa\u9519\uff0c\u8bf7\u5237\u65b0\u91cd\u8bd5')
  }
}

window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason)
})

app.use(createPinia())
app.use(router)
setupDirectives(app)
app.mount('#app')
