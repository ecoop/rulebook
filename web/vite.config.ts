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
      '/ask': 'http://localhost:8000',
      '/meta': 'http://localhost:8000',
    },
  },
})
