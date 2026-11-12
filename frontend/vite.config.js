import { defineConfig } from 'vite'

// In dev (`npm run dev`) API calls are proxied to Flask on :8000.
export default defineConfig({
  server: {
    port: 5173,
    proxy: { '/api': process.env.API_URL || 'http://localhost:8000' },
  },
  build: { outDir: 'dist' },
})
