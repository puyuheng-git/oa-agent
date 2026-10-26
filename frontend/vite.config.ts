/// <reference types="vitest" />
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': resolve(__dirname, 'src') } },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        setup: resolve(__dirname, 'setup/index.html'),
        admin: resolve(__dirname, 'admin/index.html'),
        chat: resolve(__dirname, 'chat/index.html'),
      },
    },
  },
  server: {
    proxy: {
      '/v1': backend,
      '/healthz': backend,
      '/readyz': backend,
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
  },
})
