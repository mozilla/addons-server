/** @type {import('stylelint').Config} */
export default {
  ignoreFiles: [
    // Ignore non CSS/LESS files
    '**/*.!(css|less)',
    // ignore vendored css
    'static/css/zamboni/jquery-ui/*',
  ],
  rules: {
    'selector-class-pattern': null, // We have PascalCase class names in the codebase
    'selector-id-pattern': null, // We have snake_case id selectors in the codebase
    'no-descending-specificity': null, // 1610 Errors .. this might be too big to fail
  },
  overrides: [
    {
      files: ['static/css/**/*.css'],
      extends: ['stylelint-config-standard'],
    },
    {
      files: ['static/css/**/*.less'],
      extends: ['stylelint-config-standard-less'],
    },
  ],
};
