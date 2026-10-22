import { defineConfig, loadEnv, type Plugin } from 'vite';
import { STATIC_SEGMENT, toViteBasePath } from './src/base.ts';

// the fallback is for a standalone build/dev run
const STATIC_URL_PREFIX = process.env.STATIC_URL_PREFIX ?? '/static/';
const ASSET_BASE = `${STATIC_URL_PREFIX}${STATIC_SEGMENT}/`;

// The SPA is also served under locale-prefixed URLs (e.g. /en-US/developers/...);
// nginx proxies those here unchanged. Vite's dev server enforces its configured
// `base` (the unprefixed segment) and rejects anything outside it, so strip the
// locale prefix before Vite's own middlewares see the request.
function serveLocalePrefixed(): Plugin {
  return {
    name: 'pinguino-serve-locale-prefixed',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url) {
          req.url = toViteBasePath(req.url);
        }
        next();
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  // Under `make up` the browser reaches Vite through nginx (Vite's port isn't
  // published), so the HMR socket must target that proxied port. The compose
  // service sets VITE_HMR_CLIENT_PORT=80. Standalone `npm run dev` has no proxy,
  // so leave it unset and the HMR socket uses the dev-server port directly.
  const hmrClientPort = loadEnv(mode, '.', 'VITE_').VITE_HMR_CLIENT_PORT;

  return {
    base: ASSET_BASE,
    plugins: [serveLocalePrefixed()],
    server: {
      host: true,
      port: 5273,
      strictPort: true,
      // Requests arrive via nginx with the Host of the whole site (olympia.test).
      allowedHosts: true,
      hmr: hmrClientPort ? { clientPort: Number(hmrClientPort) } : true,
    },
    build: {
      // Write straight into the repo's static files location (static/pinguino/) so
      // Django/nginx/cdn can serve the build output directly.
      // Relative to this config at src/pinguino/devhub/.
      outDir: `../../../static/${STATIC_SEGMENT}`,
      manifest: true,
      emptyOutDir: true,
    },
  };
});
