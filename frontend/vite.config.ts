import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/generate': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/run': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
