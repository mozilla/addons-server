import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import '../../../components/addon-listing';
import '../../../components/addon-manage-header';
import { type Addon, addonQuery } from '../../../data';

// Each tab is its own URL under /pinguino/addon/:slug/<tab>, so a tab is
// linkable and survives reload. The bare add-on URL defaults to the listing
// editor.
const TABS = [
  { value: 'versions', label: 'Versions' },
  { value: 'feed', label: 'Activity & Notification' },
  { value: 'edit', label: 'Listing Details' },
  { value: 'statistics', label: 'Statistics' },
] as const;

type TabValue = (typeof TABS)[number]['value'];
const DEFAULT_TAB: TabValue = 'edit';
const isTab = (v: string): v is TabValue => TABS.some((t) => t.value === v);

@customElement('devhub-addon')
export class DevhubAddon extends LitElement {
  @property() slug = '';
  @property() tab: string = DEFAULT_TAB;

  #addon = addonQuery(this, () => this.slug);

  static styles = css`
    :host {
      display: block;
    }
    moz-segmented-control {
      margin-block: var(--space-large) var(--space-xlarge);
    }
    .stub {
      padding: var(--space-xxlarge) var(--space-large);
      text-align: center;
      color: var(--text-color-deemphasized, GrayText);
      background-color: var(--background-color-box);
      border-radius: var(--border-radius-medium);
    }
  `;

  get #activeTab(): TabValue {
    return isTab(this.tab) ? this.tab : DEFAULT_TAB;
  }

  #selectTab = (e: Event) => {
    const { value } = (e as CustomEvent<{ value: string }>).detail;
    const url = `/pinguino/addon/${this.slug}/${value}`;
    if (location.pathname !== url) {
      history.pushState({}, '', url);
      // Nudge the shell router (it re-renders on popstate) to match the URL.
      dispatchEvent(new PopStateEvent('popstate'));
    }
  };

  #panel(addon: Addon) {
    switch (this.#activeTab) {
      case 'edit':
        return html`<addon-listing .addon=${addon}></addon-listing>`;
      default: {
        const label = TABS.find((t) => t.value === this.#activeTab)?.label;
        return html`<div class="stub">
          ${label} - coming in a later ticket.
        </div>`;
      }
    }
  }

  render() {
    const result = this.#addon();
    if (result.isPending) {
      return html`<p class="stub">Loading…</p>`;
    }
    const a = result.data;
    if (!a) {
      return html`
        <p><a href="/pinguino/">&larr; Back to dashboard</a></p>
        <p class="stub">We couldn't find that add-on.</p>
      `;
    }

    return html`
      <addon-manage-header .addon=${a}></addon-manage-header>

      <moz-segmented-control
        value=${this.#activeTab}
        @moz-segmented-control:change=${this.#selectTab}
        label="Manage sections"
        fill
      >
        ${TABS.map(
          (t) => html`<moz-segmented-control-item
            value=${t.value}
            label=${t.label}
          ></moz-segmented-control-item>`,
        )}
      </moz-segmented-control>

      ${this.#panel(a)}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-addon': DevhubAddon;
  }
}
