import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

const DOTTED_ROUTE_PREFIXES = ['/momentum/']

function dottedClientRouteFallbackPlugin(): Plugin {
  const shouldRewrite = (
    method: string | undefined,
    rawUrl: string | undefined,
    acceptHeader: string | string[] | undefined
  ): boolean => {
    if (method !== 'GET' && method !== 'HEAD') return false
    if (!rawUrl) return false

    const path = rawUrl.split('?')[0] || ''
    if (!path.includes('.')) return false
    if (!DOTTED_ROUTE_PREFIXES.some((prefix) => path.startsWith(prefix))) return false

    const accept = Array.isArray(acceptHeader) ? acceptHeader.join(',') : (acceptHeader || '')
    return accept.includes('text/html')
  }

  const rewriteMiddleware = (
    req: { method?: string; url?: string; headers?: Record<string, string | string[] | undefined> },
    _res: unknown,
    next: () => void
  ) => {
    if (shouldRewrite(req.method, req.url, req.headers?.accept)) {
      req.url = '/index.html'
    }
    next()
  }

  return {
    name: 'dotted-client-route-fallback',
    configureServer(server) {
      server.middlewares.use(rewriteMiddleware)
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewriteMiddleware)
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), dottedClientRouteFallbackPlugin()],
  // Reduce noisy dev-server output (e.g., repetitive HMR update lines)
  logLevel: 'warn',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
