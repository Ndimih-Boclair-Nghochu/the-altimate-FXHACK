import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
  version: string
}

/**
 * Backend origin for the dev/preview proxy. Read from the Node environment only
 * (deliberately NOT a VITE_ variable, so it is never bundled into client code).
 */
const backendUrl = process.env.BACKEND_URL ?? 'http://localhost:8000'

const proxy = {
  '/api': { target: backendUrl, changeOrigin: true },
  '/ws': { target: backendUrl, changeOrigin: true, ws: true },
}

/**
 * Security headers applied by `vite preview` so the production bundle is exercised
 * under the same policy nginx serves. Keep in sync with nginx.conf.
 * (Not applied to `vite dev`: the dev server relies on inline scripts for HMR.)
 */
const securityHeaders = {
  'Content-Security-Policy': [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; '),
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
    headers: securityHeaders,
  },
  build: {
    target: 'es2023',
    // Never inline assets as data: URIs, so the CSP can stay at font-src 'self'.
    assetsInlineLimit: 0,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    unstubGlobals: true,
  },
})
