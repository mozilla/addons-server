import type { IconName } from '@mozilla/lit-web-components';
import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import '../components/addon-card';
import '../components/submit-card';
import '../components/update-card';
import type { AddonKind, AddonsQuery, Update } from '../data';
import { addonsQuery, profileQuery, updatesQuery } from '../data';

interface Group {
  title: string;
  icon: IconName;
  submitLabel: string;
}

const GROUPS: Record<AddonKind, Group> = {
  extension: {
    title: 'Extensions',
    icon: 'extension',
    submitLabel: 'Submit new extension',
  },
  theme: {
    title: 'Themes',
    icon: 'themes',
    submitLabel: 'Submit new theme',
  },
};

@customElement('devhub-home')
export class DevhubHome extends LitElement {
  #profile = profileQuery(this);
  #extensions = addonsQuery(this, 'extension');
  #themes = addonsQuery(this, 'theme');
  #updates = updatesQuery(this);

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
  `;

  render() {
    const name = this.#profile().data?.name;
    const heading = name
      ? `Welcome to the Developer Hub, ${name}`
      : 'Welcome to the Developer Hub.';
    return html`
      <moz-page-header
        heading=${heading}
        description="Manage your Firefox add-ons, track reviews, and publish updates."
      ></moz-page-header>

      <app-grid columns-md="1">
        <div style="grid-column: span 7">
          <app-stack gap="xlarge">
            ${this.#group('extension', this.#extensions)}
            ${this.#group('theme', this.#themes)}
          </app-stack>
        </div>
        <div style="grid-column: span 5">
          ${this.#feed(this.#updates().data ?? [])}
        </div>
      </app-grid>
    `;
  }

  // Each section owns its request, so one kind failing or still loading leaves
  // the other readable.
  #group(kind: AddonKind, query: AddonsQuery) {
    const { title, icon, submitLabel } = GROUPS[kind];
    const { data, isError, isPending } = query();

    if (isError) {
      return html`
        <section class="section">
          <div class="count">
            <span>We couldn't load your ${title.toLowerCase()}.</span>
            <moz-button size="small" @click=${() => query.refetch()}>
              Retry
            </moz-button>
          </div>
        </section>
      `;
    }
    if (isPending) {
      return html`
        <section class="section">
          <p class="count">Loading your ${title.toLowerCase()}…</p>
        </section>
      `;
    }

    const items = data.results;
    return html`
      <section class="section">
        <p class="count">
          <moz-icon name=${icon} color="accent-primary-desaturated"></moz-icon>
          ${data.count} ${title}
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
                <moz-illustration name="kit-meditate-clouds" style="width:200px"></moz-illustration>
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
