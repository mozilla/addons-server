import { defineConfig, UserConfig } from 'vite';
import { z } from 'zod';
import inject from '@rollup/plugin-inject';
import { resolve, relative } from 'path';
import { glob } from 'glob';
import babel from '@rollup/plugin-babel';

const INPUT_DIR = './static';
const OUTPUT_DIR = './static-build';

// Any js/less file in the root directory of js/css
// is interpreted as an entrypoint and will be bundled
// and served via vite. These files can be injected
// into django templates and resolved correctly in dev/prod
const jsFiles = glob.sync('./static/js/*.js');
const cssFiles = glob.sync('./static/css/*.less');

// format inputs with unique keys
const input = [...jsFiles, ...cssFiles].reduce((acc, path) => {
  const relativePath = relative(INPUT_DIR, path);
  const entryName = relativePath.replace(/\.(js|less)$/, '');
  acc[entryName] = resolve(path);
  return acc;
}, {});

const jqueryGlobals = {
  $: 'jquery',
  jQuery: 'jquery',
};

const envSchema = z.object({
  ENV: z.enum(['local', 'build', 'dev', 'stage', 'prod']),
  STATIC_URL_PREFIX: z.string(),
  VITE_MANIFEST_FILE_NAME: z.string(),
  SITE_URL: z.string().optional(),
});

const env = envSchema.parse(process.env);

export default defineConfig(({ command }) => {
  const isLocal = env.ENV === 'local';
  const isDev = command === 'serve';

  return {
    // Ensure all static assets are treated as
    // 'in-scope' assets that can be tracked by vite
    // this ensures any imported static assets are correctly
    // mapped across file transformations.
    assetsInclude: `${INPUT_DIR}/*`,
    // Only log warnings and errors
    logLevel: 'warn',
    // exclude any automatic html bundling
    appType: 'custom',
    root: resolve(INPUT_DIR),
    // When serving, use a url prefix that forwards from nginx to the vite dev-server
    // When building, use a relative path to ensure import paths can be transformed
    // independently of where the importing file ends up in the bundle
    base: isDev ? `${env.STATIC_URL_PREFIX}bundle/` : './',
    plugins: [
      // Inject jQuery globals in the bundle for usage by npm packages
      // that rely on it being globally available.
      inject({
        exclude: ['**/*.less'],
        ...jqueryGlobals,
      }),
    ],
    build: {
      // Disable inline assets. For performance reasons we want to serve
      // all static assets from dedicated URLs which in production will
      // be cached in our CDN. The incremental build size is worse than
      // the increase in number of requests.
      assetsInlineLimit: 0,
      // This value should be kept in sync with settings_base.py
      // which determines where to read static file paths
      // for production URL resolution
      manifest: env.VITE_MANIFEST_FILE_NAME,
      // Ensure we always build from an empty directory to prevent stale files
      emptyOutDir: true,
      // Configurable values helpful for debugging
      copyPublicDir: true,
      // Minify the output for non local builds
      minify: 'esbuild',
      cssMinify: 'esbuild',
      // Include sourcemaps in local builds only
      sourcemap: !isDev && isLocal,
      // This value should be kept in sync with settings_base.py
      // which includes this path as a staticfiles directory
      outDir: resolve(OUTPUT_DIR),
      rollupOptions: {
        input,
        output: {
          format: 'es',
          // Isolate vendor code into a separate chunk to avoid
          // polluting the UMD functions in legacy modules with the
          // rollup defined shims for module.exports / exports;
          manualChunks: (id) => {
            if (id.includes('node_modules')) {
              return 'vendor';
            }
          },
        },
        plugins: [
          // Use babel to ensure compatibility with all specified browsers
          babel({
            extensions: ['.js', '.less'],
            // any helper code injected by babel will be bundled
            // along with the rest of the code
            babelHelpers: 'bundled',
          }),
        ],
      },
    },
    css: {
      preprocessorOptions: {
        less: {
          math: 'always',
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
    server: {
      host: true,
      port: 5173,
      allowedHosts: true,
      origin: env?.SITE_URL ?? '127.0.0.1',
      strictPort: true,
    },
  } satisfies UserConfig;
});
