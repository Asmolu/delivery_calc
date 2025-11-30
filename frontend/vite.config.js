import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Все запросы, начинающиеся с /api и /quote — проксируются на бэкенд
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/quote': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
