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
    }
    .middle {
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
      flex-grow: 1;
    }
    .kind {
      font-size: 0.75rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .title {
      display: flex;
      gap: var(--space-small);
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
    .meta {
      display: flex;
      align-items: center;
      gap: var(--space-xsmall);
      font-size: var(--font-size-small);
      color: var(--text-color-deemphasized, GrayText);
    }
    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-xsmall);
      margin-bottom: auto;
    }
    .divider {
      width: 100%;
      margin: 0;
      border: none;
      opacity: 70%;
      border-top: 1px solid var(--background-color-information);
    }
  `;

  render() {
    const a = this.addon;
    const isTheme = a.kind === 'theme';
    let firstChannelDisplayed: string | undefined;
    let remainingChannels: string[] | undefined;
    return html`
      <moz-card appearance="outline">
        <div class="body">
        <div class="title">
          ${
            a.iconUrl
              ? html`<img class="logo" src=${a.iconUrl} alt="" />`
              : nothing
          }
          <div class="middle">
            <h2 class="name">${a.name}</h2>
            <moz-status-badge type=${a.status.badge}>${a.status.label}</moz-status-badge>
          </div>
          <moz-button size="small" href="${BASE}/addon/${a.slug}">
            Manage
          </moz-button>
        </div>

        ${[
          a.currentVersion,
          a.latestUnlistedVersion,
          a.latestEnterpriseVersion,
        ].map((version) => {
          if (version && firstChannelDisplayed === undefined) {
            firstChannelDisplayed = version.channel;
            remainingChannels = a.channels?.filter(
              (channel) => channel !== version.channel,
            );
            return html`<div>
                <span class="version">Version: ${version.version}</span>
                <distribution-badge distribution=${version.channel}></distribution-badge>
              </div>`;
          }
          return null;
        })}

        ${
          a.latestListedVersion &&
          a.latestListedVersion.version !== a.currentVersion?.version
            ? html`<hr class="divider"><div class="meta">
          Upcoming Version: ${a.latestListedVersion.version}
        </div>`
            : nothing
        }

        ${
          remainingChannels?.length
            ? html`<hr class="divider"><div class="meta">
          Other Versions: ${remainingChannels?.map(
            (channel) => html`<distribution-badge
                distribution=${channel}
              ></distribution-badge>`,
          )}
          </div>`
            : nothing
        }

        ${
          isTheme
            ? html`<hr class="divider"><theme-preview .addon=${a}></theme-preview>`
            : nothing
        }
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-card': AddonCard;
  }
}
