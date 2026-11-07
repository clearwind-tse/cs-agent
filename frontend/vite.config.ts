import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // 图表/动效库体积大且很少变动，单独成 chunk 便于浏览器长期缓存
        manualChunks(id) {
          if (/node_modules\/(victory-vendor|d3-|internmap|decimal\.js)/.test(id)) return 'd3'
          if (id.includes('node_modules/recharts')) return 'charts'
          if (/node_modules\/(framer-motion|motion-dom|motion-utils)/.test(id)) return 'motion'
        },
      },
    },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8100',
        changeOrigin: true
      }
    }
  }
})
