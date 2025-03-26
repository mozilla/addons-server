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
    'font-family-no-missing-generic-family-keyword': null,
    'function-linear-gradient-no-nonstandard-direction': null,
    'selector-pseudo-class-no-unknown': null,
    'declaration-block-no-shorthand-property-overrides': null,
    'selector-pseudo-element-no-unknown': null,
    'function-url-quotes': null,
    'selector-attribute-quotes': null,
    'declaration-empty-line-before': null,
    'at-rule-empty-line-before': null,
    'comment-empty-line-before': null,
    'function-name-case': null,
    'declaration-block-no-redundant-longhand-properties': null,
    'font-family-no-duplicate-names': null,
    'declaration-block-no-duplicate-properties': null,
    'value-no-vendor-prefix': null,
    'comment-whitespace-inside': null,
    'selector-no-vendor-prefix': null,
    'media-feature-range-notation': null,
    'value-keyword-case': null,
    'selector-not-notation': null,
    'declaration-property-value-keyword-no-deprecated': null,
  },
  overrides: [
    {
      files: ['static/css/**/*.less'],
      extends: ['stylelint-config-standard-less'],
    },
  ],
};
