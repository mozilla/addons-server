/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** AMO session id, sent as `Authorization: Session <id>` (see .env.example). */
  readonly VITE_AMO_SESSION_ID?: string;
  /** Author (account id or username) whose add-ons to list. */
  readonly VITE_AMO_AUTHOR?: string;
  /** API base; defaults to same-origin `/api/v5`. */
  readonly VITE_AMO_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
