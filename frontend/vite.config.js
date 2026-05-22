import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/chat': 'http://localhost:8001',
      '/reset': 'http://localhost:8001',
      '/health': 'http://localhost:8001',
      '/calculate': 'http://localhost:8001',
      '/webhook': 'http://localhost:8001',
    },
  },
})
