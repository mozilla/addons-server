import { defineConfig } from 'vite';
import { resolve, join } from 'path';

// TODO: vite is clearing the cwd on every build. that is wrong and annoying.
// also it's having trouble matching the manifest.json here and the one in the settings_base.py file.
export default defineConfig((_) => {

  const INPUT_DIR = './static';
  const OUTPUT_DIR = './static-build';

  return {
    root: resolve(INPUT_DIR),
    base: '/static/',
    server: {
      host: true,
      port: 5173,
    },
    build: {
      manifest: join(OUTPUT_DIR, 'manifest.json'),
      emptyOutDir: false,
      copyPublicDir: false,
      outDir: resolve(OUTPUT_DIR),
      rollupOptions: {
        input: {
          'common': join(INPUT_DIR, 'js/common/index.js'),
        },
      },
    },
  };
});
