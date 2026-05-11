import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',   // required for Docker
    port: 3000,
    watch: { usePolling: true }, // required for volume-mounted hot reload
  },
})
