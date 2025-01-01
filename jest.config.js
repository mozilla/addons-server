// For a detailed explanation regarding each configuration property, visit:
// https://jestjs.io/docs/en/configuration.html
export default {
  setupFiles: ['<rootDir>/tests/js/setup.js'],
  testMatch: ['<rootDir>/tests/**/*.spec.js'],
  testEnvironment: 'jsdom',
};
