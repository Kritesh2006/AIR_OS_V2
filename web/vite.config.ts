import { defineConfig, type Plugin } from 'vite';

/**
 * Content-Security-Policy for production builds (GitHub Pages cannot send
 * headers, so it goes in a <meta> tag). Everything is served from our own
 * origin: no CDNs, no analytics, no outbound connections. The dev server
 * is left without CSP because Vite's HMR injects inline scripts.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'wasm-unsafe-eval'",
  "style-src 'self'",
  "img-src 'self' data: blob:",
  "media-src 'self' blob: mediastream:",
  "connect-src 'self'",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'",
].join('; ');

function cspMeta(): Plugin {
  return {
    name: 'air-csp-meta',
    apply: 'build',
    transformIndexHtml: () => [
      { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' },
    ],
  };
}

export default defineConfig({
  // GitHub Pages serves the site under /<repo>/; the deploy job sets AIR_BASE.
  base: process.env.AIR_BASE ?? '/',
  plugins: [cspMeta()],
  build: { target: 'es2022' },
  preview: { port: 4173, strictPort: true },
});
