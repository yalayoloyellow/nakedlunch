import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The React front end for extendo. In dev, /api is proxied to the Flask backend
// (api/server.py) on port 8790. In prod, launch.py runs Flask which serves the
// built dist/ — so base is relative. (Same shape as pusher/gui, minus the SSE
// proxy tweak: extendo has no streaming — a run is one synchronous POST.)
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8790', changeOrigin: true } },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
