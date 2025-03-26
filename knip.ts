import { KnipConfig } from "knip";

export default {
  entry: ["static/js/*.js", "static/css/*.{less,css}"],
  project: ["static/**/*.{js,less,css}"],
  vite: true,
  vitest: true,
  eslint: true,
  ignoreDependencies: ["addons-linter"],
} satisfies KnipConfig;
