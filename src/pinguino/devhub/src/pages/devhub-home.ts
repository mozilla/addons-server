import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import '../components/addon-card';
import type { Addon } from '../data';
import { extensions, themes, updates } from '../data';
import '../components/submit-card';
import '../components/update-card';
import type { IconName } from '@mozilla/acorn-web-components';

@customElement('devhub-home')
export class DevhubHome extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    moz-page-header {
      display: block;
      margin-block: var(--space-xxlarge);
    }
    .section {
      padding: var(--space-xlarge);
      background-color: var(--background-color-box);
      border-radius: var(--border-radius-medium);
    }
    .count {
      display: flex;
      gap: var(--space-small);
      align-items: center;
      margin: 0 0 var(--space-small);
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .empty-updates {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-medium);
      padding: var(--space-xxlarge) var(--space-large);
      text-align: center;
      color: var(--text-color-deemphasized, GrayText);
    }
    .fox {
      font-size: 3rem;
    }
  `;

  render() {
    return html`
      <moz-page-header
        heading="Welcome to Developer Hub"
        description="Manage your Firefox add-ons, track reviews, and publish updates."
      ></moz-page-header>

      <app-grid columns-md="1">
        <div style="grid-column: span 7">${this.#addons()}</div>
        <div style="grid-column: span 5">${this.#feed()}</div>
      </app-grid>
    `;
  }

  #addons() {
    return html`
      <app-stack gap="xlarge">
        ${this.#group('Extensions', 'extension', extensions, 'Submit new extension')}
        ${this.#group('Themes', 'themes', themes, 'Submit new theme')}
      </app-stack>
    `;
  }

  #group(title: string, icon: IconName, items: Addon[], submitLabel: string) {
    return html`
      <section class="section">
        <p class="count"><moz-icon name=${icon} color="accent-primary-desaturated"></moz-icon> ${items.length} ${title}</p>
        <app-grid columns="2" columns-md="2" columns-sm="1" gap="medium">
          ${items.map((a) => html`<addon-card .addon=${a}></addon-card>`)}
          <submit-card label=${submitLabel}></submit-card>
        </app-grid>
      </section>
    `;
  }

  #feed() {
    return html`
      <app-stack gap="medium" class="section">
        <!-- TODO: Build search input component in acorn-web-components, use here -->
        <moz-input-text
          icon-start="search"
          placeholder="Search updates to find the information"
          full-width
          type="text"
        ></moz-input-text>
        ${
          updates.length > 0
            ? updates.map((u) => html`<update-card .item=${u}></update-card>`)
            : html`
              <div class="empty-updates">
                <div class="fox">🦊</div>
                <p>No updates yet, take it easy</p>
              </div>
            `
        }
      </app-stack>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-home': DevhubHome;
  }
}
