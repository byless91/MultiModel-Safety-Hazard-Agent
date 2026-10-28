import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  resolve: {
    // Root test files resolve the same packages as the application.
    dedupe: ['vue', 'vue-router', 'pinia', 'vitest', '@vue/test-utils', 'axios'],
  },
  server: {
    fs: mode === 'test' ? {
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('../test', import.meta.url)),
      ],
    } : undefined,
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://localhost:8001',
        changeOrigin: true,
      },
      '/uploads': {
        target: process.env.VITE_API_PROXY || 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts', '../test/frontend/**/*.spec.ts'],
  },
}))
