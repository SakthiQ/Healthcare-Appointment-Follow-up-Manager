import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev-only proxy so the browser talks to same-origin /api and avoids CORS.
    // In production VITE_API_BASE_URL points at the deployed backend instead.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Each test starts from the real modules: spies and stubbed env/globals are undone.
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
  },
});
