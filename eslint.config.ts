import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import vitest from "@vitest/eslint-plugin";
import js from "@eslint/js";
import prettier from 'eslint-plugin-prettier';
import simpleImportSort from 'eslint-plugin-simple-import-sort';

import { defineConfig } from "eslint/config";
import globals from 'globals';
import { includeIgnoreFile } from "@eslint/compat";
import { Linter } from "eslint";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const gitignorePath = path.resolve(__dirname, ".gitignore");

const baseConfig: Linter.Config = {
  name: 'addons-eslint-config',
  plugins: {
    prettier,
    js,
    'simple-import-sort': simpleImportSort,
  },
  languageOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  rules: {
    ...js.configs.recommended.rules,
    'no-undef': 2,
    'no-implicit-globals': 'error', // No references to gloabl variables within our own scripts
    'strict': ['error', 'global'], // all scripts run in strict mode
    'no-var': 'error', // no use of var as variable initializer (const/let only)
    'no-unused-vars': [
      'error',
      {
        vars: 'all', // check all variables including global scope
        varsIgnorePattern: '^_', // ignore any variable starting with _
        ignoreRestSiblings: true, // ignore rest parameters
        caughtErrorsIgnorePattern: '^_', // ignore any variable starting with _
      },
    ],
    'simple-import-sort/imports': 'error',
    'simple-import-sort/exports': 'error',
    'prettier/prettier': [
      'error',
      {
        arrowParens: 'always',
        singleQuote: true,
        trailingComma: 'all',
        proseWrap: 'never',
      },
    ],
  },
};

const config = defineConfig([
  // Ignore files based on .gitignore
  includeIgnoreFile(gitignorePath),
  // Ignore specific files
  {
    ignores: [
      // Don't lint vendored files
      'static/js/lib/**',
      // This file is beyond saving and is not used.
      'scripts/rewrite.js',
    ],
  },
  // static/js files
  {
    name: 'amo-js',
    files: ['**/*.js'],
    extends: [baseConfig],
    languageOptions: {
      globals: {
        ...globals.browser,
        gettext: 'readonly',
        ngettext: 'readonly',
        $: 'readonly', // Add jQuery global
      },
    },
    rules: {
      // Disable rules causing errors
      'prettier/prettier': 'off',
    },
  },
  // Specific rules for test files
  {
    name: 'amo-tests',
    files: ["tests/**"], // or any other pattern
    plugins: {
      vitest,
      prettier,
    },
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.browser,
        ...globals.vitest,
      }
    },
    extends: [vitest.configs.recommended, baseConfig],
    rules: {
      // Disable all the error-causing rules for tests
      'vitest/valid-title': 'off',
      'prettier/prettier': 'off',
    },
  },
]);

export default config;
