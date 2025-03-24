import { defineConfig } from 'vite';
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

const env = (name, defaultValue) =>
  process.env[name] || defaultValue || new Error(`${name} is not defined`);

export default defineConfig(({ command }) => {
  const isLocal = env('ENV') === 'local';
  const isDev = command === 'serve';

  const baseConfig = {
    // Ensure all static assets are treated as
    // 'in-scope' assets that can be tracked by vite
    // this ensures any imported static assets are correctly
    // mapped across file transformations.
    assetsInclude: `${INPUT_DIR}/*`,
    strict: true,
    root: resolve(INPUT_DIR),
    debug: env('DEBUG', false),
    // In dev mode, prefix 'bundle' to static file URLs
    // so that nginx knows to forward the request to the vite
    // dev server instead of serving from static files or olympia
    // Use a relative path during the build
    // this ensures that import paths can be transformed
    // independently of where the importing file ends up in the bundle
    base: './',
    resolve: {
      alias: {
        // Alias 'highcharts' to our local vendored copy
        // we cannot use npm to install due to licensing constraints
        highcharts: resolve(__dirname, 'static/js/lib/highcharts-module.js'),
      },
    },
    plugins: [
      // Inject jQuery globals in the bundle for usage by npm packages
      // that rely on it being globally available.
      inject({
        exclude: ['**/*.less'],
        ...jqueryGlobals,
      }),
    ],
    build: {
      // This value should be kept in sync with settings_base.py
      // which determines where to read static file paths
      // for production URL resolution
      manifest: env('VITE_MANIFEST_FILE_NAME'),
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
  };

  if (isDev) {
    // In dev mode, add the bundle path to direct
    // static requests to the vite dev server via nginx
    baseConfig.base = `${env('STATIC_URL_PREFIX')}bundle/`;
    // Configure the dev server in dev mode
    baseConfig.server = {
      host: true,
      port: 5173,
      allowedHosts: true,
      origin: env('SITE_URL'),
      strictPort: true,
      clearScreen: true,
    };
  }

  return baseConfig;
});
