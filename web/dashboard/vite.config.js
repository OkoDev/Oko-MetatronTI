import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// DEV-144 Stage 1.
// Dev-сервер Vite слушает 5173, бэкенд aiohttp (dashboard_server.py) — 8000.
// Все /api/* и SSE проксируются на 8000, чтобы фронтенд работал из коробки.
export default defineConfig({
  plugins: [vue()],
  // base = '/v2/' — prod bundle монтируется в aiohttp под /v2/.
  // В dev (vite serve) base всё равно '/' для удобства разработки.
  base: process.env.NODE_ENV === 'production' ? '/v2/' : '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE: вебсокеты не нужны, но потоковый ответ должен идти как есть.
        // http-proxy по умолчанию не буферизует — этого достаточно.
      },
      '/sse': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
})
