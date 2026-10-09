import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { Addon } from '../data';

// Host only (strip scheme/path) for the compact homepage link in the stats row.
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

@customElement('addon-manage-header')
export class AddonManageHeader extends LitElement {
  @property({ attribute: false }) addon!: Addon;

  static styles = css`
    :host {
      display: block;
    }
    .back {
      margin: 0 0 var(--space-small);
    }
    .back a {
      color: var(--text-color-deemphasized, GrayText);
      text-decoration: none;
    }
    .back a:hover {
      text-decoration: underline;
    }
    moz-breadcrumb-group {
      display: block;
      margin-bottom: var(--space-large);
    }
    .bar {
      display: flex;
      align-items: flex-start;
      gap: var(--space-large);
    }
    .logo {
      width: 56px;
      height: 56px;
      border-radius: var(--border-radius-medium, 8px);
      flex: none;
    }
    .body {
      flex: 1;
      min-width: 0;
    }
    h1 {
      margin: 0 0 var(--space-xsmall);
      font-size: 1.5rem;
    }
    .tagline {
      margin: 0 0 var(--space-small);
      color: var(--text-color-deemphasized, GrayText);
    }
    .stats {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-xsmall) var(--space-small);
      color: var(--text-color-deemphasized, GrayText);
    }
    .stats .sep {
      opacity: 0.5;
    }
    .stats a {
      color: var(--link-color, LinkText);
    }
    .rating {
      display: inline-flex;
      align-items: center;
      gap: var(--space-xxsmall);
    }
    .actions {
      flex: none;
      display: flex;
      align-items: center;
      gap: var(--space-small);
    }
  `;

  #stats() {
    const a = this.addon;
    const parts = [];
    if (a.rating != null) {
      parts.push(html`
        <span class="rating">
          <moz-five-star rating=${a.rating}></moz-five-star>
          ${a.rating.toFixed(1)}${
            a.reviewCount != null ? html` (${a.reviewCount} reviews)` : nothing
          }
        </span>
      `);
    }
    if (a.averageDailyUsers != null) {
      parts.push(
        html`<span>${a.averageDailyUsers.toLocaleString('en-US')} users</span>`,
      );
    }
    if (a.homepageUrl) {
      parts.push(
        html`<a href=${a.homepageUrl} target="_blank" rel="noopener"
          >${hostOf(a.homepageUrl)}</a
        >`,
      );
    }
    parts.push(html`<span>Last updated ${a.lastUpdated}</span>`);
    if (a.listingUrl) {
      parts.push(
        html`<a href=${a.listingUrl} target="_blank" rel="noopener"
          >View listing page</a
        >`,
      );
    }
    // Interleave a separator between parts.
    return parts.flatMap((p, i) =>
      i === 0 ? [p] : [html`<span class="sep">·</span>`, p],
    );
  }

  render() {
    const a = this.addon;
    const live = a.visibility === 'live';
    return html`
      <!-- TODO: Query the back to dashboard with Kate, duplicated by breadcrumb? -->
      <p class="back"><a href="/pinguino/">&lsaquo; back to dashboard</a></p>
      <moz-breadcrumb-group label="Breadcrumb">
        <moz-breadcrumb href="/pinguino/">Dashboard</moz-breadcrumb>
        <moz-breadcrumb>${a.name}</moz-breadcrumb>
      </moz-breadcrumb-group>
      <div class="bar">
        ${
          a.iconUrl
            ? html`<img class="logo" src=${a.iconUrl} alt="" />`
            : undefined
        }
        <div class="body">
          <h1>${a.name}</h1>
          ${a.summary ? html`<p class="tagline">${a.summary}</p>` : nothing}
          <div class="stats">${this.#stats()}</div>
        </div>
        <div class="actions">
          <!-- TODO: implement addon status management https://github.com/mozilla/addons/issues/16389 -->
          <moz-status-badge type=${live ? 'success' : 'ghost'}>
            ${live ? 'Live' : 'Hidden'}
          </moz-status-badge>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-manage-header': AddonManageHeader;
  }
}
