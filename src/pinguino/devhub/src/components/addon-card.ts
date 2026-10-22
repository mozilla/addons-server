import type { IconName } from 'acorn-web-components';
import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { BASE } from '../base';
import type { Addon, AddonDistribution, AddonVisibility } from '../data';

type Badge = { label: string; icon: IconName };

const VISIBILITY: Record<AddonVisibility, Badge> = {
  live: { label: 'Live', icon: 'show-password' },
  hidden: { label: 'Hidden', icon: 'show-password-slash' },
};
const DISTRIBUTION: Record<AddonDistribution, Badge> = {
  listed: { label: 'AMO', icon: 'globe' },
  unlisted: { label: 'Self', icon: 'home' },
  enterprise: { label: 'Enterprise', icon: 'organizational-unit' },
};

@customElement('addon-card')
export class AddonCard extends LitElement {
  @property({ attribute: false }) addon!: Addon;

  static styles = css`
    :host {
      display: block;
      height: 100%;
    }
    /* Fill the grid cell so the body's margin-top:auto pins the tags to the
     * bottom and cards in a row stay equal height. */
    moz-card,
    moz-card::part(card),
    moz-card::part(content) {
      height: 100%;
    }
    .body {
      box-sizing: border-box;
      height: 100%;
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
    }
    .top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-small);
    }
    .kind {
      font-size: 0.75rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .title {
      display: flex;
      align-items: center;
      gap: var(--space-xsmall);
    }
    .name {
      margin: 0;
      font-weight: 600;
    }
    .bar {
      height: 10px;
      border-radius: 999px;
    }
    .logo {
      width: 32px;
      height: 32px;
      border-radius: var(--border-radius-small, 4px);
    }
    .preview {
      width: 100%;
      height: 96px;
      object-fit: cover;
      border-radius: var(--border-radius-medium, 8px);
    }
    .meta {
      display: flex;
      align-items: center;
      gap: var(--space-xsmall);
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-xsmall);
      margin-bottom: auto;
    }
  `;

  render() {
    const a = this.addon;
    const isTheme = a.kind === 'theme';
    return html`
      <moz-card appearance="outline">
        <div class="body">
          <div class="top">
          <span class="kind">${isTheme ? 'Theme' : 'Extension'}</span>
          <moz-button size="small" href="${BASE}/addon/${a.slug}">
            Manage
          </moz-button>
        </div>

        ${
          isTheme
            ? html`
              <h2 class="name">${a.name}</h2>
              ${
                a.previewUrl
                  ? html`<img class="preview" src=${a.previewUrl} alt="" />`
                  : html`<div class="bar" style="background: ${a.gradient};"></div>`
              }
            `
            : html`
              <div class="title">
                ${
                  a.iconUrl
                    ? html`<img class="logo" src=${a.iconUrl} alt="" />`
                    : undefined
                }
                <h2 class="name">${a.name}</h2>
              </div>
            `
        }

        <div class="meta">
          <span>Status</span>
          <moz-status-badge type="success">${a.statusLabel}</moz-status-badge>
        </div>
        <div class="meta">Current version: ${a.version}</div>
        <div class="meta">Last updated: ${a.lastUpdated}</div>

        <div class="tags">
          <moz-status-badge
            type="ghost"
            icon-start=${VISIBILITY[a.visibility].icon}
          >
            ${VISIBILITY[a.visibility].label}
          </moz-status-badge>
           ${a.channels?.map((channel) => {
             return html`
                  <moz-status-badge
                    type="ghost"
                    icon-start=${DISTRIBUTION[channel].icon}
                  >
                    ${DISTRIBUTION[channel].label}
                  </moz-status-badge>
                    `;
           })}
        </div>
        </div>
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-card': AddonCard;
  }
}
