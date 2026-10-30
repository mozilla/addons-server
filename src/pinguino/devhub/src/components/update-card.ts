import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import { BASE } from '../base';
import type { Update } from '../data';
import '../foundations/badges';
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
      padding: var(--space-large);
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
      gap: var(--space-medium);
      flex: 1;
      min-width: 0;
    }
    .title p {
      margin: 0;
      padding: 0;
    }
    .title .headline {
      font-weight: 600;
    }
    .addon-name {
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
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

  // Where "View" goes: the Versions tab for an entry about a version, the
  // add-on otherwise. The title's own links point at the public listing, so
  // this is the DevHub counterpart. There's no per-version page to deep-link
  // to yet, and the activity API doesn't give us a version id either.
  #viewHref() {
    const { addonSlug, version } = this.item;
    const addon = `${BASE}/addon/${addonSlug}`;
    return version ? `${addon}/versions` : addon;
  }

  render() {
    const u = this.item;
    const status = u.versionStatus;
    return html`
      <div class="card">
        <!-- title and message are HTML from the activity API; sanitize to a
             link-only allowlist before rendering. The add-on link lives in the
             title. -->
        <div class="head">
          <span class="title">
            <!-- TODO: Fix type error in acorn-web-components, this should be a valid use -->
            <moz-status-dot
              icon
              type=${status?.badge ?? 'information'}
            ></moz-status-dot>
            <span>
              <p class="headline">${unsafeHTML(sanitizeHTML(u.title, ALLOWED_TAGS))}</p>
              ${
                u.addonName
                  ? html`<p class="addon-name">${u.addonName}</p>`
                  : nothing
              }
            </span>
          </span>
          <moz-button size="small" href=${this.#viewHref()}>View</moz-button>
        </div>
        <p class="message">${unsafeHTML(sanitizeHTML(u.message, ALLOWED_TAGS))}</p>
        <div class="foot">
          <span>${u.user ? `${u.date} by ${u.user}` : u.date}</span>
          ${u.version.length ? html`<span>Version: ${u.version}</span>` : nothing}
          ${
            status
              ? html`
                <moz-status-badge type=${status.badge}>
                  ${status.label}
                </moz-status-badge>
              `
              : nothing
          }
          ${
            u.channel
              ? html`<distribution-badge
                  distribution=${u.channel}
                ></distribution-badge>`
              : nothing
          }
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
