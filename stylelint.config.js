/** @type {import('stylelint').Config} */
export default {
  extends: 'stylelint-config-standard',
  ignoreFiles: [
    // Ignore non CSS/LESS files
    '**/*.!(css|less)',
    // ignore vendored css
    'static/css/zamboni/jquery-ui/*',
  ],
  rules: {
    'selector-class-pattern': null,
    'selector-id-pattern': null,
    'no-descending-specificity': null,
    'no-duplicate-selectors': null,
    'declaration-property-value-no-unknown': null,
  },
  overrides: [
    {
      files: ['static/css/**/*.less'],
      extends: ['stylelint-config-standard-less'],
    },
  ],
};
