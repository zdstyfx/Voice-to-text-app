import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE 流需要关闭代理缓冲，否则事件会被攒批后才送达
        configure: (proxy) => {
          proxy.on('proxyRes', (_proxyRes, req) => {
            if (req.url?.includes('/stream')) {
              _proxyRes.headers['x-accel-buffering'] = 'no';
              _proxyRes.headers['cache-control'] = 'no-cache';
            }
          });
        },
      },
    },
  },
  build: {
    outDir: '../shokztype/web/static',
    emptyOutDir: true,
  },
})
