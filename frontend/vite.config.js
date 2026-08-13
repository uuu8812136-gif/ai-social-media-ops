import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const elementPlusIconNames = new Set([
  'ArrowDown', 'Calendar', 'Check', 'CircleCloseFilled', 'Collection',
  'Connection', 'DataAnalysis', 'Document', 'Download', 'Edit', 'Folder',
  'Loading', 'Phone', 'Plus', 'Promotion', 'Refresh', 'Search', 'Setting',
  'Shop', 'SwitchButton', 'UserFilled', 'VideoCamera',
])

function elementPlusIconResolver(name) {
  if (elementPlusIconNames.has(name)) {
    return { name, from: '@element-plus/icons-vue' }
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_TARGET || 'http://127.0.0.1:8002'
  const devPort = Number(process.env.FRONTEND_DEV_PORT) || 5173
  return {
  plugins: [
    vue(),
    Components({
      dts: false,
      resolvers: [ElementPlusResolver({ importStyle: 'css' }), elementPlusIconResolver],
    }),
  ],
  server: {
    port: devPort,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
            if (id.includes('element-plus') || id.includes('@element-plus')) return undefined
            if (id.includes('vue') || id.includes('pinia') || id.includes('@vue')) return 'vue-vendor'
            return 'vendor'
          }
        },
      },
    },
  },
  }
})
