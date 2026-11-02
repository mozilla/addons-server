/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base; defaults to same-origin `/api/v5`. */
  readonly VITE_AMO_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
