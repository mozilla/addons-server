import type { IconName } from '@mozilla/acorn-web-components';
import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { Addon, AddonDistribution, AddonVisibility } from '../data';

type Badge = { label: string; icon: IconName };

// acorn has no literal office/building glyph, so Enterprise uses `briefcase`.
const VISIBILITY: Record<AddonVisibility, Badge> = {
  live: { label: 'Live', icon: 'show-password' },
  hidden: { label: 'Hidden', icon: 'show-password-slash' },
};
const DISTRIBUTION: Record<AddonDistribution, Badge> = {
  amo: { label: 'AMO', icon: 'globe' },
  self: { label: 'Self', icon: 'home' },
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
    .card {
      box-sizing: border-box;
      height: 100%;
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
      padding: var(--space-large);
      border: 1px solid var(--icon-color-accent-primary-desaturated);
      border-radius: var(--border-radius-medium, 8px);
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
      /* font-size: 1rem; */
      font-weight: 600;
    }
    .bar {
      height: 10px;
      border-radius: 999px;
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
      margin-top: auto;
    }
  `;

  render() {
    const a = this.addon;
    const isTheme = a.kind === 'theme';
    return html`
      <div class="card">
        <div class="top">
          <span class="kind">${isTheme ? 'Theme' : 'Extension'}</span>
          <moz-button size="small" href="/pinguino/addon/${a.slug}">
            Manage
          </moz-button>
        </div>

        ${
          isTheme
            ? html`
              <h2 class="name">${a.name}</h2>
              <!-- TODO: should use proper theme image -->
              <div class="bar" style="background: ${a.gradient};"></div>
            `
            : html`
              <div class="title">
                <!-- <moz-icon name=${a.icon}></moz-icon> -->
                <h2 class="name">${a.name}</h2>
              </div>
            `
        }

        <!-- TODO: extensions should show extension logo -->
        <div class="meta">
          <span>Status</span>
          <moz-status-badge type="success">${a.statusLabel}</moz-status-badge>
        </div>
        <div class="meta">Current version: ${a.version}</div>

        <div class="tags">
          <moz-status-badge
            type="ghost"
            icon-start=${VISIBILITY[a.visibility].icon}
          >
            ${VISIBILITY[a.visibility].label}
          </moz-status-badge>
          <moz-status-badge
            type="ghost"
            icon-start=${DISTRIBUTION[a.distribution].icon}
          >
            ${DISTRIBUTION[a.distribution].label}
          </moz-status-badge>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-card': AddonCard;
  }
}
