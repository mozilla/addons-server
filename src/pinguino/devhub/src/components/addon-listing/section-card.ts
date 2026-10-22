import { html, LitElement, nothing, type TemplateResult, unsafeCSS } from 'lit';
import { property, state } from 'lit/decorators.js';
import type { Addon } from '../../data';
import { routeApiError } from '../../foundations/form';
// Styles live in a sibling .css file; `?inline` brings them in as a string that
// unsafeCSS adopts (the project's convention). One CSSResult instance is shared
// across every section card and the shell.
import stylesText from './addon-listing.css?inline';
import { SECTION, type SectionId } from './sections';

export const sharedStyles = unsafeCSS(stylesText);

// Base for the four listing-section cards. Holds the add-on, the shared
// edit/save/error state, the stylesheet, and the card-head/row/link/runAction
// helpers; each subclass renders its own <moz-card> body.
export abstract class SectionCard extends LitElement {
  @property({ attribute: false }) addon!: Addon;
  @state() protected editing = false;
  @state() protected saving = false;
  @state() protected error = '';

  static styles = sharedStyles;

  // Renders the heading for a section's card from its SECTION metadata.
  // `actions` overrides the default (inert) Edit button; cards pass their Edit
  // or Save/Cancel controls.
  protected cardHead(id: SectionId, actions?: TemplateResult) {
    const { title, description, icon } = SECTION[id];
    return html`<div slot="heading" class="card-head">
      <div>
        <span class="card-title">
          <moz-icon name=${icon}></moz-icon>
          <h2>${title}</h2>
        </span>
        <p class="sub">${description}</p>
      </div>
      ${actions ?? html`<moz-button size="small">Edit</moz-button>`}
    </div>`;
  }

  // Edit / Save+Cancel for cards backed by a FormController (listing, technical).
  protected draftActions(
    form: { editing: boolean; saving: boolean; cancel: () => void },
    onEdit: () => void,
    onSave: () => void,
  ) {
    return form.editing
      ? html`<div class="card-actions">
          <moz-button
            size="small"
            variant="ghost"
            ?disabled=${form.saving}
            @click=${() => form.cancel()}
            >Cancel</moz-button
          >
          <moz-button
            size="small"
            variant="primary"
            ?disabled=${form.saving}
            @click=${onSave}
            >${form.saving ? 'Saving…' : 'Save'}</moz-button
          >
        </div>`
      : html`<moz-button size="small" @click=${onEdit}>Edit</moz-button>`;
  }

  // Always renders the label; falls back to a muted dash so the section keeps
  // the design's shape even when a value is absent.
  protected row(label: string, value: unknown): TemplateResult {
    const empty = value == null || value === '';
    return html`<div class="field">
      <dt>${label}</dt>
      <dd>${empty ? html`<span class="muted">—</span>` : value}</dd>
    </div>`;
  }

  protected link(url: string | undefined) {
    return url
      ? html`<a href=${url} target="_blank" rel="noopener">${url}</a>`
      : null;
  }

  // Routes a failure to the card's error bar. These cards have no single
  // API-field-keyed input to attach to (authors rows, screenshot captions), so
  // field errors are folded into the one general message via routeApiError.
  protected setError(e: unknown) {
    const { error, fieldErrors } = routeApiError(e);
    const parts = [
      error,
      ...Object.entries(fieldErrors).map(([field, msg]) => `${field}: ${msg}`),
    ].filter(Boolean);
    this.error = parts.join(' • ') || 'Something went wrong.';
  }

  // Runs a one-off action that persists immediately, toggling saving/error.
  protected runAction(fn: () => Promise<unknown>) {
    this.saving = true;
    this.error = '';
    fn()
      .catch((e) => this.setError(e))
      .finally(() => {
        this.saving = false;
      });
  }

  protected errorBar(message: string = this.error) {
    return message
      ? html`<moz-message-bar type="error">${message}</moz-message-bar>`
      : nothing;
  }
}
