import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Main UI — dev port 5174, production build served at root by API
export default defineConfig({
  plugins: [react()],
  base: process.env.NODE_ENV === 'production' ? '/static/' : '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      '/chat': 'http://localhost:8000',
      '/config': 'http://localhost:8000',
      '/events': 'http://localhost:8000',
      '/debug': 'http://localhost:8000',
      '/internal': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/users': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
    },
  },
})
