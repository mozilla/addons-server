import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import type { Update } from '../data';
import { sanitizeHTML } from '../utils/sanitizeHTML';

// The activity title/message are HTML from the API; the only markup we expect
// (and allow) is the link to the add-on.
const ALLOWED_TAGS = ['a'];

@customElement('update-card')
export class UpdateCard extends LitElement {
  // Not `update`: that's a LitElement lifecycle method.
  @property({ attribute: false }) item!: Update;

  static styles = css`
    :host {
      display: block;
    }
    .card {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
      padding: var(--space-medium) var(--space-large);
      border-radius: var(--border-radius-medium, 8px);
      background: var(--background-color-canvas);
    }
    .head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-small);
    }
    .title {
      display: flex;
      align-items: center;
      gap: var(--space-small);
      font-weight: 600;
    }
    .title p {
      margin: 0;
      padding: 0;
    }
    .message {
      margin: 0;
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .foot {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-xsmall);
      font-size: 0.8rem;
      color: var(--text-color-deemphasized, GrayText);
    }
  `;

  render() {
    const u = this.item;
    return html`
      <div class="card">
        <!-- title and message are HTML from the activity API; sanitize to a
             link-only allowlist before rendering. The add-on link lives in the
             title. -->
        <div class="head">
          <span class="title">
            <moz-status-dot
              icon
              type=${u.approved ? 'success' : 'warning'}
            ></moz-status-dot>
            <p>
              ${unsafeHTML(sanitizeHTML(u.title, ALLOWED_TAGS))}
            </p>
          </span>
          <moz-button size="small" href="/pinguino/addon/${u.addonSlug}">View</moz-button>
        </div>
        <p class="message">${unsafeHTML(sanitizeHTML(u.message, ALLOWED_TAGS))}</p>
        <div class="foot">
          ${
            u.version.length
              ? html`<span>Version ${u.version}</span>`
              : undefined
          }
          ${
            u.versionStatus
              ? html`
                <moz-status-badge type=${u.approved ? 'success' : 'warning'}>
                  ${u.versionStatus}
                </moz-status-badge>
              `
              : undefined
          }
          ${u.tags.map((t) => html`<span>${t}</span>`)}
          <span>${u.date}</span>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'update-card': UpdateCard;
  }
}
