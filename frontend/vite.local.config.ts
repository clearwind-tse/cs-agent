import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 临时本地配置：把代理指向本项目后端(8300)，避免与占用 8000/5173 的其他项目冲突。
// 不修改原 vite.config.ts；用完后可删除本文件。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5300,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8300',
        changeOrigin: true
      }
    }
  }
})
