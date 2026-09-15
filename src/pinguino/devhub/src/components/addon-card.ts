import buttonTokens from '@mozilla/acorn-web-components/tokens/button.css?inline';
import { css, html, LitElement, unsafeCSS } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { Addon } from '../data';

@customElement('addon-card')
export class AddonCard extends LitElement {
  @property({ attribute: false }) addon!: Addon;

  static styles = [
    unsafeCSS(buttonTokens),
    css`
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
      /* A router link (intercepted by @lit-labs/router) dressed as a button. */
      .manage {
        display: inline-flex;
        align-items: center;
        padding: var(--space-xxsmall) var(--space-small);
        font-size: 0.85rem;
        text-decoration: none;
        color: var(--button-text-color);
        background: var(--button-background-color);
        border-radius: var(--border-radius-medium, 8px);
      }
      .manage:hover {
        background: var(--button-background-color-hover);
      }
    `,
  ];

  render() {
    const a = this.addon;
    const isTheme = a.kind === 'theme';
    return html`
      <div class="card">
        <div class="top">
          <span class="kind">${isTheme ? 'Theme' : 'Extension'}</span>
          <!-- TDO: moz-button should support a/href -->
          <a class="manage" href="/pinguino/addon/${a.slug}">Manage</a>
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
          <!-- TODO: switch to a status-badge component -->
          <moz-badge type="success">${a.statusLabel}</moz-badge>
        </div>
        <div class="meta">Current version: ${a.version}</div>

        <!-- TODO: Tags should not be chips -->
        <div class="tags">
          ${a.tags.map((t) => html`<moz-chip>${t}</moz-chip>`)}
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
