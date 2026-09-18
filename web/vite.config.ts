import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// 开发服务器把 /api 代理到本地 API 端口（可用 API_PORT 覆盖）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.API_PORT ?? 8000}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
  },
});
