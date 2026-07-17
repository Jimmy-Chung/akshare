import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3005,
    strictPort: true,
    allowedHosts: ['.jimmy-jam.com'],
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest, request) => {
            proxyRequest.setHeader('X-Dashboard-Original-Host', request.headers.host || '')
          })
        }
      }
    }
  }
})
