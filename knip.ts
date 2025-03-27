import { KnipConfig } from "knip";

const CSS_IMPORT_REGEX = /@import\s*(?:\([^)]*\)\s*)?["']([^"']+)["']/g;

function compileLess(text: string): string {
  return text.replace(CSS_IMPORT_REGEX, (_, path) => {
    // imports without a file extension should be treated as .less files
    // source: https://lesscss.org/features/#import-atrules-feature-file-extensions
    if (path.split('.').length === 1) {
      return `import "./${path}.less";`
    }

    return `import "${path}";`
  });
}

function compileCss(text: string) {
  return text.replace(CSS_IMPORT_REGEX, (_, path) => {
    return `import "${path}";`
  })
}

export default {
  entry: ["static/js/*.js", "static/css/*.{less,css}"],
  project: ["static/**/*.{js,less,css}!"],
  vite: true,
  vitest: true,
  eslint: true,
  ignoreDependencies: ["addons-linter"],
  compilers: {
    // Custom compilers for less/css files
    less: compileLess,
    css: compileCss,
  },
} satisfies KnipConfig;
