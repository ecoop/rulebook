import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The proxy lets the frontend do `fetch('/ask')` in dev and have the request
// forwarded to the FastAPI backend on :8000. Cleaner than CORS + hard-coded
// URLs in the client, and it means the built app can be served next to the
// API under a single origin in production without any code change.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // 127.0.0.1 rather than localhost: on Node 17+ / macOS,
      // `localhost` can resolve to ::1 first, but uvicorn binds IPv4 by
      // default — the mismatch shows up as ECONNREFUSED on every proxied
      // request. Pinning to 127.0.0.1 avoids that.
      '/ask': 'http://127.0.0.1:8000',
      '/meta': 'http://127.0.0.1:8000',
      '/feedback': 'http://127.0.0.1:8000',
      '/gold': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
      '/usage': 'http://127.0.0.1:8000',
      '/diagnostics': 'http://127.0.0.1:8000',
    },
  },
})
