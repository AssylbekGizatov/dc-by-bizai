import { defineConfig } from 'vite'

// Страница — обычный HTML/CSS/JS: скрипты и стили лежат в public/ и копируются в dist/ как есть.
// В dev-режиме /api и /triage проксируются на FastAPI; Host браузера сохраняется для same-origin проверки API.
const api = { target: 'http://127.0.0.1:8000', changeOrigin: false }

export default defineConfig({
  server: {
    host: '127.0.0.1',
    proxy: { '/api': api, '/triage': api },
  },
  build: { sourcemap: false },
})
