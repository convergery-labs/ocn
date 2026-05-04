import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        '^/(auth|news|signal)/': {
          target: env.VITE_API_BASE_URL ?? 'http://localhost:8004',
          changeOrigin: true,
        },
      },
    },
  };
});
