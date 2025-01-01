import { defineConfig } from 'vite';
import { resolve } from 'path';

const INPUT_DIR = './static';
const OUTPUT_DIR = './static/bundle';

const inputs = (paths) => paths.reduce((acc, path) => {
  const key = path.split('.')[0];
  acc[key] = resolve(INPUT_DIR, path);
  return acc;
}, {});

export default defineConfig((_) => {
  return {
    root: resolve(INPUT_DIR),
    base: '/static/bundle/',
    server: {
      host: true,
      port: 5173,
    },
    build: {
      manifest: 'manifest.json',
      emptyOutDir: true,
      copyPublicDir: false,
      outDir: resolve(OUTPUT_DIR),
      rollupOptions: {
        input: inputs([
          'js/common/index.js',
          'js/common/fonts.js',
          'css/common/fonts.less',
          'css/common/footer.less',
          'css/restyle/restyle.less',
          'css/devhub/new-landing/base.less',
          'css/zamboni/index.less',
          'css/zamboni/stats.less',
          'css/zamboni/devhub.less',
          'css/zamboni/reviewers/index.less',
          'js/common/index.js',
        ]),
      },
    },
  };
});
