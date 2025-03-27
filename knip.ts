import { KnipConfig } from "knip";

const CSS_IMPORT_REGEX = /@import\s*(?:url\()?(?:\([^)]*\)\s*)?["']([^"']+)["'](?:\))?/g;

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
  ignoreDependencies: [
    "addons-linter",
    // Disable rules causing errors
    "jqmodal",
    "jquery-pjax",
    "highcharts",
    "source-map",
  ],
  ignore: [
    // Disable rules causing errors
    "static/css/admin/larger_raw_id.css",
    "static/css/devhub/search.less",
    "static/css/impala/footer.less",
    "static/css/impala/nojs.css",
    "static/css/moz_header/footer.css",
    "static/css/shield_study_10/main.css",
    "static/css/shield_study_11/main.css",
    "static/css/shield_study_12/main.css",
    "static/css/shield_study_13/main.css",
    "static/css/shield_study_15/main.css",
    "static/css/shield_study_14/main.css",
    "static/css/shield_study_16/main.css",
    "static/css/shield_study_3/main.css",
    "static/css/shield_study_4/main.css",
    "static/css/shield_study_5/main.css",
    "static/css/shield_study_6/main.css",
    "static/css/shield_study_7/main.css",
    "static/css/shield_study_8/main.css",
    "static/css/shield_study_9/main.css",
    "static/css/zamboni/blocklist.css",
    "static/css/zamboni/nick.css",
    "static/css/zamboni/themes_review.less",
    "static/css/zamboni/translations/trans.css",
    "static/js/lib/highcharts-module.js",
    "static/js/lib/highcharts.src.js",
  ],
  compilers: {
    // Custom compilers for less/css files
    less: compileLess,
    css: compileCss,
  },
} satisfies KnipConfig;
