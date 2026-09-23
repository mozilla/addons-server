import type { IconName } from '@mozilla/acorn-web-components';
import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import '../components/addon-card';
import '../components/submit-card';
import '../components/update-card';
import type { Addon, Update } from '../data';
import { addonsQuery, profileQuery, updatesQuery } from '../data';
import meditateClouds from '../foundations/illustrations/kit-meditate-clouds.svg';

@customElement('devhub-home')
export class DevhubHome extends LitElement {
  #profile = profileQuery(this);
  #addons = addonsQuery(this);
  #updates = updatesQuery(this, () => this.#addons());

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
    .illustration {
      width: 180px;
      height: auto;
    }
  `;

  render() {
    const name = this.#profile().data?.name;
    const heading = name
      ? `Welcome to the Developer Hub, ${name}`
      : 'Welcome to the Developer Hub.';
    const addons = this.#addons();
    return html`
      <moz-page-header
        heading=${heading}
        description="Manage your Firefox add-ons, track reviews, and publish updates."
      ></moz-page-header>

      ${
        addons.isError
          ? html`
            <div class="count">
              <span>We couldn't load your add-ons.</span>
              <moz-button size="small" @click=${() => this.#addons.refetch()}>
                Retry
              </moz-button>
            </div>
          `
          : addons.isPending
            ? html`<p class="count">Loading your add-ons…</p>`
            : html`
              <app-grid columns-md="1">
                <div style="grid-column: span 7">
                  ${this.#addonSections(addons.data ?? [])}
                </div>
                <div style="grid-column: span 5">
                  ${this.#feed(this.#updates().data ?? [])}
                </div>
              </app-grid>
            `
      }
    `;
  }

  #addonSections(addons: Addon[]) {
    const extensions = addons.filter((a) => a.kind === 'extension');
    const themes = addons.filter((a) => a.kind === 'theme');
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
        <p class="count">
          <moz-icon name=${icon} color="accent-primary-desaturated"></moz-icon>
          ${items.length} ${title}
        </p>
        ${
          items.length > 0
            ? html`
          <app-grid columns="2" columns-md="2" columns-sm="1" gap="medium">
            ${items.map((a) => html`<addon-card .addon=${a}></addon-card>`)}
            <submit-card label=${submitLabel}></submit-card>
          </app-grid>
        `
            : html`
          <app-grid columns="1" gap="medium">
            <submit-card label=${submitLabel}></submit-card>
          </app-grid>
        `
        }
      </section>
    `;
  }

  #feed(updates: Update[]) {
    return html`
      <app-stack gap="medium" class="section">
        ${
          updates.length > 0
            ? html`
          <moz-input-search
            placeholder="Search updates to find the information"
            full-width
          ></moz-input-search>
        `
            : undefined
        }
        ${
          updates.length > 0
            ? updates.map((u) => html`<update-card .item=${u}></update-card>`)
            : html`
              <div class="empty-updates">
                <img class="illustration" src=${meditateClouds} alt="" />
                <h3>No updates yet, take it easy</h3>
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
