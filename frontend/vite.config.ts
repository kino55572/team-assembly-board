import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// В разработке API проксируется на локальный сервер FastAPI (порт 8000 по умолчанию).
export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    proxy: { '/api': process.env.API_URL ?? 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
