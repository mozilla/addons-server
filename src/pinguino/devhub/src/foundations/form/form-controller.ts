import type { ReactiveController, ReactiveControllerHost } from 'lit';
import { ApiError } from '../../data/http';

// Splits a failure into an inline per-field map and a general message, so forms
// (and bespoke editors) route errors the same way. Field keys match the API.
export function routeApiError(e: unknown): {
  error: string;
  fieldErrors: Record<string, string>;
} {
  if (e instanceof ApiError) {
    const hasFields = Object.keys(e.fields).length > 0;
    // Prefer the general detail for the bar; if there's nothing general but
    // also no field errors to show inline, fall back to the summary message.
    return {
      error: e.detail || (hasFields ? '' : e.message),
      fieldErrors: e.fields,
    };
  }
  return {
    error: e instanceof Error ? e.message : 'Something went wrong.',
    fieldErrors: {},
  };
}

// Drives an edit form: holds the working draft and edit/save/error state, and
// orchestrates submit + error routing. Attach to any LitElement; read its
// state in render and call its methods from event handlers.
export class FormController<Draft extends object>
  implements ReactiveController
{
  editing = false;
  saving = false;
  error = '';
  fieldErrors: Record<string, string> = {};
  draft = {} as Draft;

  #host: ReactiveControllerHost;

  constructor(host: ReactiveControllerHost) {
    this.#host = host;
    host.addController(this);
  }

  hostConnected() {}

  start(initial: Draft) {
    this.draft = initial;
    this.error = '';
    this.fieldErrors = {};
    this.editing = true;
    this.#host.requestUpdate();
  }

  cancel() {
    this.editing = false;
    this.error = '';
    this.fieldErrors = {};
    this.#host.requestUpdate();
  }

  set<K extends keyof Draft>(key: K, value: Draft[K]) {
    this.draft = { ...this.draft, [key]: value };
    this.#host.requestUpdate();
  }

  value<K extends keyof Draft>(key: K): Draft[K] {
    return this.draft[key];
  }

  fieldError(name: string): string {
    return this.fieldErrors[name] ?? '';
  }

  // Runs the caller's API calls, leaving edit mode on success and routing any
  // failure onto the inputs (field errors) and/or the general error.
  async submit(run: (draft: Draft) => Promise<void>) {
    this.saving = true;
    this.error = '';
    this.fieldErrors = {};
    this.#host.requestUpdate();
    try {
      await run(this.draft);
      this.editing = false;
    } catch (e) {
      const routed = routeApiError(e);
      this.error = routed.error;
      this.fieldErrors = routed.fieldErrors;
    } finally {
      this.saving = false;
      this.#host.requestUpdate();
    }
  }
}
