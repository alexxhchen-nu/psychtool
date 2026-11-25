import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// @types/node is not installed (offline sandbox); declare just what we use.
declare const process: { env: Record<string, string | undefined> }

// Dev server proxies /api to the FastAPI backend (psychtool.server, port 8000).
// When PSYCHTOOL_SESSION_TOKEN is set (the same value the backend was started
// with — see README), the proxy attaches it so the backend's token check
// passes without the server-rendered index.html meta tag.
const sessionToken = process.env.PSYCHTOOL_SESSION_TOKEN

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: sessionToken ? { 'X-Psychtool-Token': sessionToken } : undefined,
      },
    },
  },
})
