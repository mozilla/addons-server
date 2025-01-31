import { defineConfig } from 'vite';
import inject from '@rollup/plugin-inject';
import { resolve } from 'path';
import { glob } from 'glob';

const INPUT_DIR = './static';
const OUTPUT_DIR = './static-build';

// Any js/less file in the root directory of js/css
// is interpreted as an entrypoint and will be bundled
// and served via vite. These files can be injected
// into django templates and resolved correctly in dev/prod
const jsFiles = glob.sync('./static/js/*.js');
const cssFiles = glob.sync('./static/css/*.less');

const inputs = [...jsFiles, ...cssFiles].reduce((acc, path) => {
  const key = path.split('.')[0];
  acc[key] = path;
  return acc;
}, {});

export default defineConfig(({ command }) => {
  return {
    root: resolve(INPUT_DIR),
    // In dev mode, prefix 'bundle' to static file URLs
    // so that nginx knows to forward the request to the vite
    // dev server instead of serving from static files or olympia
    base: `/static/${command === 'serve' ? 'bundle/' : ''}`,
    server: {
      host: true,
      port: 5173,
      allowedHosts: true,
    },
    plugins: [
      // Inject jQuery globals in the bundle for usage by npm packages
      // that rely on it being globally available.
      inject({
        $: 'jquery',
        jQuery: 'jquery',
      }),
    ],
    build: {
      // This value should be kept in sync with settings_base.py
      // which determines where to read static file paths
      // for production URL resolution
      manifest: 'manifest.json',
      // Ensure we always build from an empty directory to prevent stale files
      emptyOutDir: true,
      // Configurable values helpful for debugging
      copyPublicDir: true,
      minify: false,
      sourcemap: true,
      // This value should be kept in sync with settings_base.py
      // which includes this path as a staticfiles directory
      outDir: resolve(OUTPUT_DIR),
      rollupOptions: {
        input: inputs,
        format: 'es',
        output: {
          // Isolate vendor code into a separate chunk to avoid
          // polluting the UMD functions in legacy modules with the
          // rollup defined shims for module.exports / exports;
          manualChunks: (id) => {
            if (id.includes('node_modules')) {
              return 'vendor';
            }
          },
        },
      },
    },
    css: {
      preprocessorOptions: {
        less: {
          math: 'always',
          // relativeUrls: true,
          javascriptEnabled: true,
        },
      },
    },
    optimizeDeps: {
      include: [
        '@claviska/jquery-minicolors',
        'jquery',
        'jquery-ui',
        'jquery.browser',
        'jquery.cookie',
        'timeago',
      ],
    },
  };
});
