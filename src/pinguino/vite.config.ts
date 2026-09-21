import { defineConfig, loadEnv } from 'vite';

const BASE = '/pinguino/';

export default defineConfig(({ mode }) => {
  // Under `make up` the browser reaches Vite through nginx (Vite's port isn't
  // published), so the HMR socket must target that proxied port. The compose
  // service sets VITE_HMR_CLIENT_PORT=80. Standalone `npm run dev` has no proxy,
  // so leave it unset and the HMR socket uses the dev-server port directly.
  const hmrClientPort = loadEnv(mode, '.', 'VITE_').VITE_HMR_CLIENT_PORT;

  return {
    base: BASE,
    server: {
      host: true,
      port: 5273,
      strictPort: true,
      // Requests arrive via nginx with the Host of the whole site (olympia.test).
      allowedHosts: true,
      hmr: hmrClientPort ? { clientPort: Number(hmrClientPort) } : true,
    },
    build: {
      outDir: 'dist',
      manifest: true,
      emptyOutDir: true,
    },
  };
});
