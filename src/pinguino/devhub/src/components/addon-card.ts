import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { BASE } from '../base';
import type { Addon } from '../data';
import '../foundations/badges';
import './theme-preview';

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
      justify-content: space-between;
    }
    .top {
      display: flex;
      gap: var(--space-small);
    }
    .title {
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
      flex-grow: 1;
    }
    .kind {
      font-size: 0.75rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .name {
      margin: 0;
      font-size: var(--font-size-large);
      font-weight: 600;
    }
    .logo {
      width: 32px;
      height: 32px;
      padding: 12px;
      background: var(--background-color-canvas);
      border-radius: var(--border-radius-small, 4px);
    }
    .version {
      vertical-align: middle;
    }
    .bottom {
      border-top: 1px solid var(--background-color-information);
      padding-top: var(--space-medium);
    }
    .upcoming {
      display: flex;
      align-items: center;
      gap: var(--space-xsmall);
      font-size: 0.9rem; /* --font-size-small is too small */
      color: var(--text-color-deemphasized, GrayText);
    }
    .pending-review {
      color: var(--icon-color-warning);
    }
  `;

  render() {
    const a = this.addon;
    const isTheme = a.kind === 'theme';
    const mostRelevantVersion =
      a.currentVersion || a.latestUnlistedVersion || a.latestEnterpriseVersion;

    return html`
      <moz-card appearance="outline">
        <div class="body">
          <div class="top">
            ${
              !isTheme && a.iconUrl
                ? html`<img class="logo" src=${a.iconUrl} alt="" />`
                : nothing
            }
            <div class="title">
              <h2 class="name">${a.name}</h2>
              <moz-status-badge type=${a.status.badge}>${a.status.label}</moz-status-badge>
            </div>
            <moz-button size="small" href="${BASE}/addon/${a.slug}">
              Manage
            </moz-button>
          </div>

          ${
            mostRelevantVersion
              ? html`<div class="middle">
                <span class="version">Version: ${mostRelevantVersion.version}</span>
                <distribution-badge distribution=${mostRelevantVersion.channel}></distribution-badge>
              </div>`
              : nothing
          }

          <div class="bottom">
            ${
              isTheme
                ? html`<theme-preview .addon=${a}></theme-preview>`
                : html`<div class="upcoming">Upcoming version: ${
                    a.latestListedVersion &&
                    a.latestListedVersion.version !== a.currentVersion?.version
                      ? html`${a.latestListedVersion?.version} <span class="pending-review">Pending review</span>`
                      : '—'
                  }</div>`
            }
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
