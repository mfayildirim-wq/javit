/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const KERN = 'http://127.0.0.1:8765';

export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: KERN, changeOrigin: true },
      '/ws': { target: KERN, ws: true, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: KERN, changeOrigin: true },
      '/ws': { target: KERN, ws: true, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
    css: false,
  },
});
